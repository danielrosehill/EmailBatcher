---
name: queue-update
description: Queue an email update to a client for the next batched send instead of emailing now; mark urgent to override and send at once.
---

# Queue an update

Use this whenever the user wants to "send", "tell", "update" or "let X know" for a recipient managed by EmailBatcher. The update waits in the queue and goes out inside the next consolidated email.

## The CLI

All work goes through `emailbatcher.py` (stdlib Python, JSON on stdout). Call it as `$EB` below:

- Once a deployment exists, use the copy inside it: `python3 <deployment>/bin/emailbatcher.py`.
- Before that (setup), use `${CLAUDE_PLUGIN_ROOT}/scripts/emailbatcher.py`, or fetch `https://raw.githubusercontent.com/danielrosehill/EmailBatcher/main/scripts/emailbatcher.py` if the plugin is not installed locally.

The workstation client config (deployment path + who this user is) lives at
`${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json`.
If it is missing, run the `setup` skill first.

## Inputs

- Recipient id (`$EB status` lists them). Match the client name the user says to an id.
- The update text. Write it as a standalone item, a few sentences, in the voice the client will read. No greeting or sign-off; the batch adds those.
- Optional short `--subject` (one line headline) and `--topic` (project or workstream; items are grouped under it).
- Urgency. Only mark `--urgent` when the user says it cannot wait for the next release.

## Steps

1. Write the update through stdin:
   ```bash
   $EB queue <recipient> --subject "<headline>" --topic "<topic>" --body - <<'TXT'
   <update text>
   TXT
   ```
   Drop `--topic` if there is none.
2. Report the id and `next_release` (convert to the deployment timezone) in one line.
3. **Urgent**: add `--urgent`. With a server runner, it goes out on the next tick (minutes). If the user needs it out this second, or there is no server, add `--send-now` too; that needs transport credentials on this machine.

## Notes

- Queueing commits and pushes to the shared deployment repo; team members see it after their next pull.
- To change or cancel an update before release: `release-batch` skill, withdraw step.
