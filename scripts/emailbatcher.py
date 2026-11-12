#!/usr/bin/env python3
"""EmailBatcher: hold outbound email updates in a queue and release one
consolidated email per recipient on a schedule, with an urgent override.

Stdlib only (Python 3.9+). The queue is a directory of markdown files (the
"deployment"), normally a private git repo shared by a team and processed by a
server that runs `tick` every few minutes. See docs/design.md.

Every command prints JSON on stdout. Exit code 0 = ok, 1 = error, 2 = partial.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import secrets
import shutil
import smtplib
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "0.1.0"
PLUGIN = "email-batcher"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---------------------------------------------------------------- helpers

def out(obj, code=0):
    print(json.dumps(obj, indent=2, default=str))
    sys.exit(code)


def fail(msg, **extra):
    out({"ok": False, "error": msg, **extra}, 1)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def slugify(s, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:n].strip("-") or "update"


def read_json(p):
    return json.loads(Path(p).read_text())


def write_json(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")


def data_root():
    """The plugin data-storage resolver:
    ${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/
    """
    base = os.environ.get("CLAUDE_USER_DATA")
    if not base:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
        base = str(Path(xdg) / "claude-plugins")
    return Path(base) / PLUGIN


def client_config():
    p = data_root() / "config.json"
    return read_json(p) if p.exists() else {}


def resolve_deployment(arg):
    path = arg or os.environ.get("EMAILBATCHER_DEPLOYMENT") or client_config().get("deployment_path")
    if not path:
        fail("No deployment. Pass --deployment, set EMAILBATCHER_DEPLOYMENT, or run the setup skill.")
    p = Path(path).expanduser()
    if not (p / "emailbatcher.json").exists():
        fail(f"{p} is not an EmailBatcher deployment (no emailbatcher.json).")
    return p


def resolve_user(arg):
    u = arg or os.environ.get("EMAILBATCHER_USER") or client_config().get("user")
    if not u:
        fail("No user identity. Pass --user or run the setup skill to write the client config.")
    return u


# ---------------------------------------------------------------- frontmatter

def parse_update(path):
    text = Path(path).read_text()
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ": " in line:
                    k, v = line.split(": ", 1)
                    meta[k.strip()] = v.strip()
                elif line.endswith(":"):
                    meta[line[:-1].strip()] = ""
            body = text[end + 5:]
    meta["urgent"] = str(meta.get("urgent", "false")).lower() == "true"
    meta["body"] = body.strip()
    meta["path"] = str(path)
    return meta


def write_update(path, meta, body):
    lines = ["---"]
    for k in ("id", "recipient", "author", "queued_at", "topic", "subject", "urgent"):
        v = meta.get(k, "")
        if isinstance(v, bool):
            v = "true" if v else "false"
        lines.append(f"{k}: {str(v).replace(chr(10), ' ')}")
    lines.append("---")
    Path(path).write_text("\n".join(lines) + "\n\n" + body.strip() + "\n")


# ---------------------------------------------------------------- deployment model

class Deployment:
    def __init__(self, root: Path):
        self.root = root
        self.cfg = read_json(root / "emailbatcher.json")
        self.tz = ZoneInfo(self.cfg.get("timezone", "UTC"))

    def users(self):
        return {p.stem: read_json(p) for p in sorted((self.root / "users").glob("*.json"))}

    def recipients(self):
        return {p.stem: read_json(p) for p in sorted((self.root / "recipients").glob("*.json"))}

    def recipient(self, rid):
        p = self.root / "recipients" / f"{rid}.json"
        if not p.exists():
            fail(f"Unknown recipient '{rid}'.", known=list(self.recipients()))
        return read_json(p)

    def pending(self, rid):
        d = self.root / "queue" / rid
        items = [parse_update(p) for p in sorted(d.glob("*.md"))] if d.exists() else []
        return sorted(items, key=lambda m: m.get("queued_at", ""))

    def state(self, rid):
        p = self.root / "state" / f"{rid}.json"
        return read_json(p) if p.exists() else {}

    def set_state(self, rid, **kv):
        s = self.state(rid)
        s.update(kv)
        write_json(self.root / "state" / f"{rid}.json", s)

    # --- git sync (no-op when the deployment is not a git repo with a remote)
    def is_git(self):
        if not (self.root / ".git").exists():
            return False
        r = subprocess.run(["git", "-C", str(self.root), "remote"], capture_output=True, text=True)
        return bool(r.stdout.strip())

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=check)

    def pull(self):
        if self.is_git():
            self.git("pull", "--rebase", "--autostash", "-q")

    def commit_push(self, message):
        if not (self.root / ".git").exists():
            return False
        # a missing pathspec makes `git add` fail outright, so only name dirs that exist
        dirs = [d for d in ("queue", "sent", "state", "withdrawn", "users", "recipients", "bin")
                if (self.root / d).exists()]
        self.git("add", "-A", "--", *dirs, "emailbatcher.json")
        if not self.git("diff", "--cached", "--quiet", check=False).returncode:
            return False
        self.git("commit", "-q", "-m", message)
        if self.is_git():
            for _ in range(3):
                if self.git("push", "-q", check=False).returncode == 0:
                    return True
                self.git("pull", "--rebase", "-q", check=False)
            fail("git push failed after 3 attempts", deployment=str(self.root))
        return True


@contextlib.contextmanager
def locked(root: Path):
    with open(root / ".emailbatcher.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ---------------------------------------------------------------- scheduling

def next_slot(cadence, after: datetime, tz: ZoneInfo):
    """First scheduled release strictly after `after`, or None for manual cadence."""
    if cadence.get("type", "daily") == "manual":
        return None
    hh, mm = (int(x) for x in cadence.get("at", "17:00").split(":"))
    days = cadence.get("days") or DAYS
    allowed = {DAYS.index(d[:3].lower()) for d in days}
    local = after.astimezone(tz)
    for i in range(0, 15):
        day = (local + timedelta(days=i)).date()
        if day.weekday() not in allowed:
            continue
        slot = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        if slot > local:
            return slot
    return None


def due_reason(dep: Deployment, rid, rec, items, now):
    """Why the non-urgent queue for rid should be released now, or None."""
    normal = [m for m in items if not m["urgent"]]
    if not normal:
        return None, None
    oldest = parse_iso(normal[0]["queued_at"])
    slot = next_slot(rec.get("cadence", {}), oldest, dep.tz)
    th = rec.get("thresholds", {})
    if slot and now >= slot:
        return "schedule", slot
    if th.get("max_items") and len(normal) >= int(th["max_items"]):
        return "max_items", slot
    if th.get("max_age_hours") and now - oldest >= timedelta(hours=float(th["max_age_hours"])):
        return "max_age", slot
    return None, slot


# ---------------------------------------------------------------- rendering

def render(dep: Deployment, rid, rec, items, urgent=False):
    users = dep.users()
    now_local = now_utc().astimezone(dep.tz)
    multi_author = len({m.get("author") for m in items}) > 1
    label = rec.get("cadence", {}).get("label") or {
        "daily": "Daily update", "weekly": "Weekly update", "manual": "Update"
    }.get(rec.get("cadence", {}).get("type", "daily"), "Update")

    if urgent and len(items) == 1:
        subject = f"{rec.get('urgent_subject_prefix', '[Urgent]')} {items[0].get('subject') or label}".strip()
    else:
        tmpl = rec.get("subject_template") or "{label}: {name}, {date}"
        subject = tmpl.format(label=label, name=rec.get("name", rid), date=now_local.strftime("%-d %b %Y"))
        if urgent:
            subject = f"{rec.get('urgent_subject_prefix', '[Urgent]')} {subject}"

    def entry(m):
        when = parse_iso(m["queued_at"]).astimezone(dep.tz).strftime("%a %-d %b, %H:%M")
        who = users.get(m.get("author"), {}).get("name", m.get("author", ""))
        head = m.get("subject") or "(no subject)"
        meta = f"{who}, {when}" if multi_author else when
        return f"* {head}  ({meta})\n\n" + "\n".join("  " + ln if ln else "" for ln in m["body"].splitlines())

    parts = []
    greeting = rec.get("greeting")
    if greeting:
        parts.append(greeting)
    urgent_items = [m for m in items if m["urgent"]]
    normal_items = [m for m in items if not m["urgent"]]
    if urgent_items and normal_items:
        parts.append("URGENT\n\n" + "\n\n".join(entry(m) for m in urgent_items))
    elif urgent_items:
        normal_items = urgent_items
    topics = {}
    for m in normal_items:
        topics.setdefault(m.get("topic") or "", []).append(m)
    if len(topics) > 1 and "" in topics:
        topics["General"] = topics.pop("")  # untopiced items last, under their own heading
    for topic, ms in topics.items():
        block = "\n\n".join(entry(m) for m in ms)
        parts.append(f"{topic.upper()}\n\n{block}" if topic else block)
    sig = rec.get("signature") or dep.cfg.get("signature")
    if sig:
        parts.append(sig)
    body = "\n\n".join(parts).strip() + "\n"

    if rec.get("consolidation", dep.cfg.get("consolidation", "digest")) == "summary" and not (urgent and len(items) == 1):
        cmd = dep.cfg.get("summariser_command")
        if cmd:
            try:
                r = subprocess.run(cmd, shell=True, input=body, capture_output=True, text=True, timeout=300,
                                   env={**os.environ, "EMAILBATCHER_RECIPIENT": rec.get("name", rid)})
                if r.returncode == 0 and r.stdout.strip():
                    body = r.stdout.strip() + "\n"
            except subprocess.TimeoutExpired:
                pass  # fall back to the deterministic digest
    return subject, body


# ---------------------------------------------------------------- transports

def build_message(dep, rec, subject, body):
    sender = rec.get("from") or dep.cfg["sender"]
    msg = EmailMessage()
    msg["From"] = formataddr((sender.get("name", ""), sender["email"]))
    msg["To"] = ", ".join(rec["to"])
    if rec.get("cc"):
        msg["Cc"] = ", ".join(rec["cc"])
    reply_to = rec.get("reply_to") or dep.cfg.get("reply_to")
    if reply_to:
        msg["Reply-To"] = ", ".join(reply_to) if isinstance(reply_to, list) else reply_to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender["email"].split("@")[-1])
    msg.set_content(body)
    return msg


def send(dep: Deployment, rec, msg: EmailMessage, dry_run=False):
    t = dep.cfg.get("transport", {"type": "file"})
    kind = "file" if dry_run else t.get("type", "file")
    if kind == "file":
        outbox = dep.root / "outbox"
        outbox.mkdir(exist_ok=True)
        p = outbox / f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}.eml"
        p.write_bytes(bytes(msg))
        return {"transport": "file", "path": str(p)}
    if kind == "smtp":
        host, port = t["host"], int(t.get("port", 587))
        user = t.get("username") or os.environ.get("EMAILBATCHER_SMTP_USER")
        pw = os.environ.get("EMAILBATCHER_SMTP_PASSWORD")
        cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with cls(host, port, timeout=60) as s:
            if port != 465:
                s.starttls()
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)
        return {"transport": "smtp", "message_id": msg["Message-ID"]}
    if kind == "resend":
        key = os.environ.get("EMAILBATCHER_RESEND_API_KEY")
        if not key:
            raise RuntimeError("EMAILBATCHER_RESEND_API_KEY is not set")
        payload = {"from": msg["From"], "to": rec["to"], "subject": msg["Subject"], "text": msg.get_content()}
        if rec.get("cc"):
            payload["cc"] = rec["cc"]
        if msg["Reply-To"]:
            payload["reply_to"] = [a.strip() for a in msg["Reply-To"].split(",")]
        req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "User-Agent": f"email-batcher/{VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return {"transport": "resend", "id": json.loads(r.read()).get("id")}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Resend HTTP {e.code}: {e.read().decode()[:300]}")
    raise RuntimeError(f"Unknown transport '{kind}'")


def release(dep: Deployment, rid, items, reason, dry_run=False, urgent=False):
    rec = dep.recipient(rid)
    subject, body = render(dep, rid, rec, items, urgent=urgent)
    msg = build_message(dep, rec, subject, body)
    result = send(dep, rec, msg, dry_run=dry_run)
    if dry_run:
        return {"recipient": rid, "dry_run": True, "subject": subject, "items": len(items), **result}
    batch = f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{'urgent' if urgent else reason}"
    bdir = dep.root / "sent" / rid / batch
    bdir.mkdir(parents=True, exist_ok=True)
    for m in items:
        shutil.move(m["path"], bdir / Path(m["path"]).name)
    (bdir / "email.txt").write_text(f"Subject: {subject}\nTo: {msg['To']}\n\n{body}")
    write_json(bdir / "meta.json", {"sent_at": iso(now_utc()), "reason": reason, "urgent": urgent,
                                    "subject": subject, "items": [m["id"] for m in items], **result})
    dep.set_state(rid, last_release=iso(now_utc()), last_batch=batch, last_error=None)
    return {"recipient": rid, "batch": batch, "subject": subject, "items": len(items), **result}


# ---------------------------------------------------------------- commands

def cmd_init(a):
    root = Path(a.path).expanduser()
    if (root / "emailbatcher.json").exists():
        fail(f"{root} already holds a deployment.")
    for d in ("users", "recipients", "queue", "sent", "state", "bin"):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / ".gitkeep").touch()
    cfg = {
        "version": VERSION,
        "name": a.name,
        "timezone": a.timezone,
        "sender": {"email": a.sender_email, "name": a.sender_name or ""},
        "transport": {"type": a.transport},
        "consolidation": "digest",
        "summariser_command": None,
        "signature": None,
    }
    if a.transport == "smtp":
        cfg["transport"].update({"host": a.smtp_host, "port": a.smtp_port})
    write_json(root / "emailbatcher.json", cfg)
    (root / ".gitignore").write_text(".emailbatcher.lock\noutbox/\n.env\n")
    shutil.copy2(Path(__file__), root / "bin" / "emailbatcher.py")
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=False)
    out({"ok": True, "deployment": str(root), "config": cfg})


def cmd_configure_client(a):
    root = Path(a.deployment).expanduser()
    if not (root / "emailbatcher.json").exists():
        fail(f"{root} is not a deployment.")
    if not (root / "users" / f"{a.user}.json").exists():
        fail(f"User '{a.user}' has no profile in this deployment. Add it first (add-user).")
    write_json(data_root() / "config.json", {"deployment_path": str(root), "user": a.user})
    out({"ok": True, "client_config": str(data_root() / "config.json"), "deployment_path": str(root), "user": a.user})


def cmd_add_user(a):
    dep = Deployment(resolve_deployment(a.deployment))
    p = dep.root / "users" / f"{a.id}.json"
    prof = read_json(p) if p.exists() else {}
    prof.update({k: v for k, v in {"name": a.name, "email": a.email, "role": a.role}.items() if v is not None})
    write_json(p, prof)
    dep.commit_push(f"emailbatcher: user {a.id}") if a.sync else None
    out({"ok": True, "user": a.id, "profile": prof})


def cmd_add_recipient(a):
    dep = Deployment(resolve_deployment(a.deployment))
    p = dep.root / "recipients" / f"{a.id}.json"
    rec = read_json(p) if p.exists() else {"cadence": {}, "thresholds": {}}
    for k, v in {"name": a.name, "greeting": a.greeting, "subject_template": a.subject_template,
                 "consolidation": a.consolidation, "urgent_policy": a.urgent_policy, "signature": a.signature}.items():
        if v is not None:
            rec[k] = v
    if a.to:
        rec["to"] = [x.strip() for x in a.to.split(",") if x.strip()]
    if a.cc is not None:
        rec["cc"] = [x.strip() for x in a.cc.split(",") if x.strip()]
    if a.from_email:
        rec["from"] = {"email": a.from_email, "name": a.from_name or ""}
    cad = rec.setdefault("cadence", {})
    if a.cadence:
        cad["type"] = a.cadence
    if a.at:
        cad["at"] = a.at
    if a.days:
        cad["days"] = [d.strip()[:3].lower() for d in a.days.split(",")]
    if cad.get("type") == "weekly" and not cad.get("days"):
        cad["days"] = ["fri"]
    th = rec.setdefault("thresholds", {})
    if a.max_items is not None:
        th["max_items"] = a.max_items
    if a.max_age_hours is not None:
        th["max_age_hours"] = a.max_age_hours
    if not rec.get("to"):
        fail("A recipient needs at least one --to address.")
    for d in cad.get("days", []):
        if d not in DAYS:
            fail(f"Bad day '{d}'. Use {DAYS}.")
    write_json(p, rec)
    (dep.root / "queue" / a.id).mkdir(parents=True, exist_ok=True)
    (dep.root / "queue" / a.id / ".gitkeep").touch()
    dep.commit_push(f"emailbatcher: recipient {a.id}") if a.sync else None
    out({"ok": True, "recipient": a.id, "config": rec})


def cmd_queue(a):
    dep = Deployment(resolve_deployment(a.deployment))
    user = resolve_user(a.user)
    dep.recipient(a.recipient)
    body = sys.stdin.read() if a.body == "-" else a.body
    if not body or not body.strip():
        fail("Empty body.")
    with locked(dep.root):
        if a.sync:
            dep.pull()
        ts = now_utc()
        uid = f"{ts.strftime('%Y%m%dT%H%M%SZ')}-{user}-{secrets.token_hex(2)}"
        meta = {"id": uid, "recipient": a.recipient, "author": user, "queued_at": iso(ts),
                "topic": a.topic or "", "subject": a.subject or "", "urgent": a.urgent}
        d = dep.root / "queue" / a.recipient
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{uid}-{slugify(a.subject or body.splitlines()[0])}.md"
        write_update(path, meta, body)
        sent = None
        if a.urgent and a.send_now:
            sent = _send_urgent(dep, a.recipient, dry_run=False)
        pushed = dep.commit_push(f"emailbatcher: queue {uid}{' URGENT' if a.urgent else ''}") if a.sync else False
    rec = dep.recipient(a.recipient)
    slot = next_slot(rec.get("cadence", {}), ts, dep.tz) if not a.urgent else None
    out({"ok": True, "id": uid, "path": str(path), "urgent": a.urgent, "pushed": pushed,
         "next_release": iso(slot) if slot else None, "sent": sent})


def _send_urgent(dep, rid, dry_run):
    rec = dep.recipient(rid)
    items = dep.pending(rid)
    urgent = [m for m in items if m["urgent"]]
    if not urgent:
        return []
    results = []
    if rec.get("urgent_policy", "alone") == "flush":
        results.append(release(dep, rid, items, "urgent-flush", dry_run=dry_run, urgent=True))
    else:
        for m in urgent:
            results.append(release(dep, rid, [m], "urgent", dry_run=dry_run, urgent=True))
    return results


def cmd_status(a):
    dep = Deployment(resolve_deployment(a.deployment))
    now = now_utc()
    rows = []
    for rid, rec in dep.recipients().items():
        if a.recipient and rid != a.recipient:
            continue
        items = dep.pending(rid)
        reason, slot = due_reason(dep, rid, rec, items, now)
        st = dep.state(rid)
        rows.append({
            "recipient": rid, "name": rec.get("name"), "cadence": rec.get("cadence"),
            "pending": len(items), "urgent_pending": sum(m["urgent"] for m in items),
            "oldest": items[0]["queued_at"] if items else None,
            "next_release": iso(slot) if slot else None,
            "next_release_local": slot.strftime("%a %-d %b %H:%M %Z") if slot else None,
            "due_now": reason, "last_release": st.get("last_release"), "last_error": st.get("last_error"),
            "items": [{"id": m["id"], "author": m.get("author"), "subject": m.get("subject"),
                       "topic": m.get("topic"), "urgent": m["urgent"], "queued_at": m["queued_at"]}
                      for m in items] if a.verbose else None,
        })
    out({"ok": True, "deployment": str(dep.root), "now": iso(now), "recipients": rows})


def cmd_preview(a):
    dep = Deployment(resolve_deployment(a.deployment))
    rec = dep.recipient(a.recipient)
    items = dep.pending(a.recipient)
    if not items:
        out({"ok": True, "recipient": a.recipient, "pending": 0, "preview": None})
    subject, body = render(dep, a.recipient, rec, items)
    msg = build_message(dep, rec, subject, body)
    out({"ok": True, "recipient": a.recipient, "pending": len(items), "from": msg["From"], "to": msg["To"],
         "cc": msg["Cc"], "subject": subject, "body": body})


def cmd_release(a):
    dep = Deployment(resolve_deployment(a.deployment))
    with locked(dep.root):
        if a.sync:
            dep.pull()
        items = dep.pending(a.recipient)
        if not items:
            out({"ok": True, "recipient": a.recipient, "released": None, "note": "queue empty"})
        try:
            res = release(dep, a.recipient, items, "manual", dry_run=a.dry_run)
        except Exception as e:  # noqa: BLE001
            fail(f"send failed: {e}", recipient=a.recipient)
        if a.sync and not a.dry_run:
            dep.commit_push(f"emailbatcher: release {a.recipient} (manual)")
    out({"ok": True, "released": res})


def cmd_withdraw(a):
    dep = Deployment(resolve_deployment(a.deployment))
    with locked(dep.root):
        if a.sync:
            dep.pull()
        hits = list((dep.root / "queue").glob(f"*/{a.id}*.md"))
        if not hits:
            fail(f"No queued update with id '{a.id}' (already sent, or wrong id).")
        dest = dep.root / "withdrawn" / hits[0].parent.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(hits[0]), dest / hits[0].name)
        if a.sync:
            dep.commit_push(f"emailbatcher: withdraw {a.id}")
    out({"ok": True, "withdrawn": a.id})


def cmd_tick(a):
    """One scheduler pass: pull, send urgent items, release due batches, push."""
    dep = Deployment(resolve_deployment(a.deployment))
    now = now_utc()
    results, errors = [], []
    with locked(dep.root):
        if a.sync:
            dep.pull()
        dep = Deployment(dep.root)  # re-read config after pull
        for rid, rec in dep.recipients().items():
            try:
                results += _send_urgent(dep, rid, dry_run=a.dry_run)
                items = [m for m in dep.pending(rid) if not m["urgent"]]
                reason, _ = due_reason(dep, rid, rec, items, now)
                if reason:
                    results.append(release(dep, rid, items, reason, dry_run=a.dry_run))
            except Exception as e:  # noqa: BLE001
                errors.append({"recipient": rid, "error": str(e)})
                if not a.dry_run:
                    dep.set_state(rid, last_error={"at": iso(now), "error": str(e)})
        if a.sync and not a.dry_run:
            dep.commit_push(f"emailbatcher: tick {iso(now)} ({len(results)} sent)")
    out({"ok": not errors, "now": iso(now), "sent": results, "errors": errors}, 2 if errors else 0)


def main():
    ap = argparse.ArgumentParser(prog="emailbatcher", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, sync=True):
        p.add_argument("--deployment")
        if sync:
            p.add_argument("--no-sync", dest="sync", action="store_false",
                           help="skip git pull/commit/push")
        return p

    p = sub.add_parser("init", help="create a new deployment directory")
    p.add_argument("path")
    p.add_argument("--name", required=True)
    p.add_argument("--sender-email", required=True)
    p.add_argument("--sender-name")
    p.add_argument("--timezone", default="UTC")
    p.add_argument("--transport", choices=["file", "smtp", "resend"], default="file")
    p.add_argument("--smtp-host")
    p.add_argument("--smtp-port", type=int, default=587)
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("configure-client", help="point this workstation at a deployment as a user")
    p.add_argument("--deployment", required=True)
    p.add_argument("--user", required=True)
    p.set_defaults(fn=cmd_configure_client)

    p = common(sub.add_parser("add-user", help="add or update a team member profile"))
    p.add_argument("id")
    p.add_argument("--name")
    p.add_argument("--email")
    p.add_argument("--role")
    p.set_defaults(fn=cmd_add_user)

    p = common(sub.add_parser("add-recipient", help="add or update a recipient (client)"))
    p.add_argument("id")
    p.add_argument("--name")
    p.add_argument("--to", help="comma-separated")
    p.add_argument("--cc", help="comma-separated; empty string clears")
    p.add_argument("--from-email")
    p.add_argument("--from-name")
    p.add_argument("--cadence", choices=["daily", "weekly", "manual"])
    p.add_argument("--at", help="HH:MM in the deployment timezone")
    p.add_argument("--days", help="comma-separated, e.g. sun,mon,tue,wed,thu")
    p.add_argument("--max-items", type=int)
    p.add_argument("--max-age-hours", type=float)
    p.add_argument("--greeting")
    p.add_argument("--signature")
    p.add_argument("--subject-template")
    p.add_argument("--consolidation", choices=["digest", "summary"])
    p.add_argument("--urgent-policy", choices=["alone", "flush"])
    p.set_defaults(fn=cmd_add_recipient)

    p = common(sub.add_parser("queue", help="stage an update for a recipient"))
    p.add_argument("recipient")
    p.add_argument("--body", required=True, help="text, or - for stdin")
    p.add_argument("--subject")
    p.add_argument("--topic")
    p.add_argument("--user")
    p.add_argument("--urgent", action="store_true")
    p.add_argument("--send-now", action="store_true", help="with --urgent: send from this machine immediately")
    p.set_defaults(fn=cmd_queue)

    p = common(sub.add_parser("status", help="pending items and next release per recipient"), sync=False)
    p.add_argument("recipient", nargs="?")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = common(sub.add_parser("preview", help="render the consolidated email without sending"), sync=False)
    p.add_argument("recipient")
    p.set_defaults(fn=cmd_preview)

    p = common(sub.add_parser("release", help="send a recipient's queue now"))
    p.add_argument("recipient")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_release)

    p = common(sub.add_parser("withdraw", help="pull a queued update before it is sent"))
    p.add_argument("id")
    p.set_defaults(fn=cmd_withdraw)

    p = common(sub.add_parser("tick", help="scheduler pass (run every few minutes on the server)"))
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_tick)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
