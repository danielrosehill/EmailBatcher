---
name: manage-team
description: Add or update EmailBatcher team member profiles (name, email, role) so several people can queue updates to the same client.
---

# Team member profiles

Each person who queues updates has `users/<id>.json` in the deployment. The id is the author tag on every queued file; the name appears in batched emails when a batch has more than one author.

## The CLI

All work goes through `emailbatcher.py` (stdlib Python, JSON on stdout). Call it as `$EB` below:

- Once a deployment exists, use the copy inside it: `python3 <deployment>/bin/emailbatcher.py`.
- Before that (setup), use `${CLAUDE_PLUGIN_ROOT}/scripts/emailbatcher.py`, or fetch `https://raw.githubusercontent.com/danielrosehill/EmailBatcher/main/scripts/emailbatcher.py` if the plugin is not installed locally.

The workstation client config (deployment path + who this user is) lives at
`${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json`.
If it is missing, run the `setup` skill first.

## Steps

1. Pick a short lowercase id (`alice`, `dr`). Confirm it is not taken: `ls <deployment>/users`.
2. `$EB add-user <id> --name "<full name>" --email <address> [--role "<role>"]`. Re-running with the same id updates only the fields given.
3. It commits and pushes. To let the new person queue from their machine, give them read/write access to the deployment repo and point them at the `setup` skill's join path.

## Notes

- Removing someone: delete `users/<id>.json` and commit. Their already-queued and sent items keep the id.
