---
name: manage-recipients
description: Add or change an EmailBatcher recipient (client) - addresses, daily/weekly cadence, send time, thresholds, urgent policy, summary mode.
---

# Recipients and release rules

A recipient is one consolidated email stream, usually one client: `recipients/<id>.json`.

## The CLI

All work goes through `emailbatcher.py` (stdlib Python, JSON on stdout). Call it as `$EB` below:

- Once a deployment exists, use the copy inside it: `python3 <deployment>/bin/emailbatcher.py`.
- Before that (setup), use `${CLAUDE_PLUGIN_ROOT}/scripts/emailbatcher.py`, or fetch `https://raw.githubusercontent.com/danielrosehill/EmailBatcher/main/scripts/emailbatcher.py` if the plugin is not installed locally.

The workstation client config (deployment path + who this user is) lives at
`${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json`.
If it is missing, run the `setup` skill first.

## Fields (all flags optional on update)

| Flag | Meaning |
|---|---|
| `--name` | Display name used in the subject |
| `--to`, `--cc` | Comma-separated addresses |
| `--from-email`, `--from-name` | Override the deployment's agreed sender for this recipient |
| `--cadence daily\|weekly\|manual` | `manual` = only on explicit release |
| `--at HH:MM` | Release time in the deployment timezone (default 17:00) |
| `--days sun,mon,...` | Which days a slot exists (daily default: every day; weekly default: fri) |
| `--max-items N` | Release early once N updates are waiting |
| `--max-age-hours H` | Release early once the oldest update is H hours old |
| `--urgent-policy alone\|flush` | Urgent update goes out on its own (default), or takes the whole queue with it |
| `--consolidation digest\|summary` | `digest` = grouped by topic, verbatim. `summary` = piped through the deployment's `summariser_command` (falls back to digest if it fails) |
| `--greeting`, `--signature`, `--subject-template` | Template text; subject placeholders `{label}`, `{name}`, `{date}` |

## Steps

1. Ask for addresses and cadence, plus the working week if it matters (Sun-Thu vs Mon-Fri).
2. `$EB add-recipient <id> --name ... --to ... --cadence ... --at ... --days ...`
3. Report back the next release time from `$EB status <id>`.

## Notes

- A batch is due at the first scheduled slot **after the oldest waiting update**. An update queued at 18:00 for a 17:00 daily goes out at 17:00 the next allowed day, not immediately.
- Empty queues send nothing.
