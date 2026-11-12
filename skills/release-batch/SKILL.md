---
name: release-batch
description: Preview, send now, or withdraw items from an EmailBatcher queue - manual release of a client's batched email ahead of schedule.
---

# Preview, release, withdraw

## The CLI

All work goes through `emailbatcher.py` (stdlib Python, JSON on stdout). Call it as `$EB` below:

- Once a deployment exists, use the copy inside it: `python3 <deployment>/bin/emailbatcher.py`.
- Before that (setup), use `${CLAUDE_PLUGIN_ROOT}/scripts/emailbatcher.py`, or fetch `https://raw.githubusercontent.com/danielrosehill/EmailBatcher/main/scripts/emailbatcher.py` if the plugin is not installed locally.

The workstation client config (deployment path + who this user is) lives at
`${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json`.
If it is missing, run the `setup` skill first.

## Preview (no send)

`$EB preview <recipient>`. Show subject, recipients and body exactly as they will go out.

## Release now

Use when the user says "release", "send the batch", "flush it" or "send <client> their update now".

1. Run the preview and show it, unless the user already said to send without looking.
2. `$EB release <recipient>`. Add `--dry-run` to write an .eml to `outbox/` instead of sending.
3. Report the subject, item count and transport result. The items move to `sent/<recipient>/<batch>/`.

Releasing from a workstation needs the transport secret in this shell's environment. If it is missing, say so. Don't move the items by hand.

## Withdraw an item

`$EB withdraw <id-prefix>` moves a queued update to `withdrawn/` so it never sends. To edit an update instead, edit its markdown file under `queue/<recipient>/`, then commit and push.

## Notes

- Sent mail cannot be recalled. Confirm the recipient before a manual release when there is any ambiguity about which client is meant.
