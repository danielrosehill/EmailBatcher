---
name: batch-status
description: Show what EmailBatcher has queued per client, who queued it, when the next batched email goes out, and any send errors.
---

# Queue status

## The CLI

All work goes through `emailbatcher.py` (stdlib Python, JSON on stdout). Call it as `$EB` below:

- Once a deployment exists, use the copy inside it: `python3 <deployment>/bin/emailbatcher.py`.
- Before that (setup), use `${CLAUDE_PLUGIN_ROOT}/scripts/emailbatcher.py`, or fetch `https://raw.githubusercontent.com/danielrosehill/EmailBatcher/main/scripts/emailbatcher.py` if the plugin is not installed locally.

The workstation client config (deployment path + who this user is) lives at
`${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json`.
If it is missing, run the `setup` skill first.

## Steps

1. Pull first so the view is current: `git -C <deployment> pull --rebase -q` (skip if not a git repo).
2. `$EB status [<recipient>] -v`
3. Report per recipient in a short table: pending count, urgent pending, next release (local time), last release, `last_error` if set. List items only if asked or if there are five or fewer.
4. A non-null `last_error` means the server's last attempt failed and the items are still queued. Say so and show the error.
