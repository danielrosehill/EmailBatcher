# Design

Status as of 2026-11-12: v0.1.0, CLI and skills built. Tested locally with the `file` transport, a two-user git flow against a bare remote, and scheduled, threshold, urgent and manual releases. Not yet tested: a real `smtp` or `resend` send, the systemd units on a server, and the `summary` consolidation mode.

## Problem

A consultant (or anyone with a frequent correspondent) produces many small updates a day. Sending each one floods the client; holding them back by hand means remembering to send. EmailBatcher is an outbound holding layer: updates are queued and released as one consolidated email per recipient on an agreed cadence (daily, weekly), with an override for the truly urgent.

## Architecture

```
 team member A ─┐  (Claude session, queue-update skill)
 team member B ─┼─► git push ─► deployment repo (private) ◄─ git pull/push ─ server: tick every 5 min ─► SMTP / Resend ─► client
 team member C ─┘                 queue/<client>/*.md                         (systemd timer or cron)
```

- **Deployment = a private git repo of markdown and JSON.** Each queued update is a separate file, so concurrent pushes from several people never conflict. Git provides transport, auth (whoever has repo access), history and an audit trail of what went out.
- **The server is the release authority.** It holds the only transport credentials, runs `tick` on a timer, and pushes the moved files back. Workstations can be off. A local-only mode (no remote, `tick` or `release` run by hand) works the same way for a solo user.
- **One stdlib Python CLI** (`scripts/emailbatcher.py`, copied into each deployment's `bin/` by `init`) does all mutation. Skills are thin wrappers that tell the agent which subcommand to run. Server and workstations need only Python 3.9+ and git.

## Deployment layout

```
emailbatcher.json          deployment: name, timezone, agreed sender, transport, consolidation, summariser_command, signature
users/<id>.json            team member profiles (name, email, role)
recipients/<id>.json       to/cc, optional from override, cadence {type, at, days}, thresholds {max_items, max_age_hours}, urgent_policy, consolidation, greeting, signature, subject_template
queue/<recipient>/<ts>-<user>-<rand>-<slug>.md     pending updates (frontmatter: id, recipient, author, queued_at, topic, subject, urgent)
sent/<recipient>/<batch>/  the released update files + email.txt + meta.json (sent_at, reason, transport result)
withdrawn/<recipient>/     updates pulled before release
state/<recipient>.json     last_release, last_batch, last_error
bin/emailbatcher.py        the runner (vendored copy)
.env                       server-only secrets (gitignored)
```

Workstation client config (pointer only): `${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json` = `{"deployment_path", "user"}`. Overridable by `EMAILBATCHER_DEPLOYMENT` / `EMAILBATCHER_USER`.

## Release rules

- A recipient's non-urgent queue is **due** when any of:
  - `schedule`: now ≥ the first cadence slot strictly after the **oldest** waiting update (so an update queued after today's slot waits for the next one; a server that was down catches up once, not once per missed slot);
  - `max_items`: the queue has reached the threshold;
  - `max_age`: the oldest update is older than `max_age_hours`.
- `manual` cadence never releases on schedule, only on thresholds or an explicit `release`.
- Empty queues send nothing.
- **Urgent override**: items with `urgent: true` are sent on the next tick, ahead of schedule. `urgent_policy: alone` (default) sends each urgent item as its own email and leaves the queue; `flush` sends the urgent item with everything waiting, urgent section first. `queue --urgent --send-now` sends from the workstation immediately (needs credentials there).
- A failed send leaves the items queued and records `state/<recipient>.json.last_error`; the next tick retries.

## Consolidation

- `digest` (default): deterministic plain text. Grouped by topic (untopiced items under GENERAL when topics are mixed), chronological, author shown only when a batch has more than one author, then the signature.
- `summary`: the digest is piped to the deployment's `summariser_command` (any shell command that reads stdin and prints the email body, e.g. a headless LLM call). On failure or timeout (300 s) the digest is sent instead.

## Transports

`file` (writes .eml to `outbox/`, the default and the dry-run path), `smtp` (STARTTLS on 587, SSL on 465; `EMAILBATCHER_SMTP_USER`/`EMAILBATCHER_SMTP_PASSWORD`), `resend` (`EMAILBATCHER_RESEND_API_KEY`). Plain-text bodies only in v0.1.

## Known limits / next steps

- Plain text only; no HTML template yet.
- Intake is through Claude sessions (git push). The original 2025 sketch used a per-client alias address (e.g. a Google Group) as the catcher; an IMAP/alias intake that turns inbound mail into queue files would let people queue by just emailing the alias.
- One runner per deployment. Two servers ticking the same repo would double-send.
- Bugs found while building: `git add` with a pathspec for a directory that does not exist yet (`withdrawn/`) fails the whole add, so commits silently included nothing. Fixed by only naming existing directories.

## Prior art (same author)

- [Client-Update-Pipeline-Notes](https://github.com/danielrosehill/Client-Update-Pipeline-Notes) (2025-11-18): original sketch, alias address + Google Group as the queue, agent summarises per period.
- [Agent-Briefing-Gateway](https://github.com/danielrosehill/Agent-Briefing-Gateway) (2026-07-30): the same mechanism pointed inbound (sub-agents to a human).
