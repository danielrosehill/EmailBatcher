---
name: setup-server
description: Deploy EmailBatcher's release runner on a server (systemd timer or cron) so queued emails go out on schedule without a workstation on.
---

# Server-side release runner

The server holds a clone of the deployment repo and runs `tick` every few minutes. Each tick pulls, sends urgent items, releases every recipient whose batch is due, then commits and pushes the moved files so team members see what went out.

## The CLI

All work goes through `emailbatcher.py` (stdlib Python, JSON on stdout). Call it as `$EB` below:

- Once a deployment exists, use the copy inside it: `python3 <deployment>/bin/emailbatcher.py`.
- Before that (setup), use `${CLAUDE_PLUGIN_ROOT}/scripts/emailbatcher.py`, or fetch `https://raw.githubusercontent.com/danielrosehill/EmailBatcher/main/scripts/emailbatcher.py` if the plugin is not installed locally.

The workstation client config (deployment path + who this user is) lives at
`${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json`.
If it is missing, run the `setup` skill first.

## Inputs

- How the agent reaches the server (local shell, SSH host, or the user's own remote-exec tool).
- Deployment repo URL; a deploy key or token with **push** access.
- Transport secret (Resend API key or SMTP credentials).

## Steps

1. On the server: Python 3.9+ and git present (`python3 --version`, `git --version`).
2. Clone the deployment, e.g. `/srv/email-batcher/<name>`, with credentials that can push. Set a git identity for the runner: `git -C <dir> config user.name "EmailBatcher" && git -C <dir> config user.email <sender address>`.
3. Write the secrets to `<dir>/.env` (gitignored by `init`), mode 600:
   ```
   EMAILBATCHER_RESEND_API_KEY=...
   # or EMAILBATCHER_SMTP_USER=... / EMAILBATCHER_SMTP_PASSWORD=...
   ```
   Read the values from the user's secret store; never echo them into the chat or a commit.
4. Dry run: `set -a; . <dir>/.env; set +a; python3 <dir>/bin/emailbatcher.py tick --deployment <dir> --dry-run`. Expect `"ok": true`.
5. Install the timer. Preferred: systemd, from this plugin's `templates/email-batcher.service` and `templates/email-batcher.timer` (replace `__DEPLOYMENT__` and `__USER__`), into `/etc/systemd/system/`, then `systemctl daemon-reload && systemctl enable --now email-batcher.timer`. Without systemd use `templates/crontab.txt`.
6. Verify: `systemctl list-timers email-batcher.timer`, then `journalctl -u email-batcher.service -n 20` after the first run shows a JSON result with `"ok": true`.
7. Write the server location and timer name into the deployment's `README.md` (create it if absent) and push, so the next person knows where releases run.

## Notes

- One runner per deployment. Two servers ticking the same repo would double-send; the file lock only protects one machine.
- Default interval is 5 minutes. That is also the worst-case delay for an urgent update unless the sender uses `--send-now`.
- Upgrading: copy the new `scripts/emailbatcher.py` over `<deployment>/bin/emailbatcher.py`, commit and push; the server picks it up on its next pull.
