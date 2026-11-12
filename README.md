# EmailBatcher

A Claude Code plugin that holds outbound email updates in a queue and sends one consolidated email per recipient on a schedule (daily, weekly, or at a threshold). If something can't wait, an urgent override sends it straight away.

It's built for consultants and small teams keeping a client informed. Several people queue updates through the day, and a server sends the client one digest at the agreed time from an agreed address, so the client isn't buried in small updates.

## How it works

- The **deployment** is a private git repo of markdown and JSON files: team profiles, recipients and their cadence, and the queue. Each queued update is its own file, so several people can push at once.
- A **server** runs `tick` every 5 minutes (systemd timer or cron). It sends urgent items, releases every batch that's due, and pushes the result back. Workstations don't need to be on.
- One stdlib Python CLI does all the work (`scripts/emailbatcher.py`). It needs no dependencies and outputs JSON.

Full design: [docs/design.md](docs/design.md).

## Skills

- `setup`: create a deployment, or join one as a team member.
- `setup-server`: install the release runner on a server.
- `manage-team`: add team member profiles.
- `manage-recipients`: client addresses, cadence, send time, thresholds, urgent policy.
- `queue-update`: queue an update for the next batch (or send it urgently).
- `batch-status`: what's pending, and when it goes out.
- `release-batch`: preview, send now, or withdraw an item.

## Installation

```bash
claude plugins install email-batcher@danielrosehill
```

## CLI quick reference

```bash
EB="python3 scripts/emailbatcher.py"
$EB init ~/repos/acme-email-batches --name "Acme" --sender-email updates@example.com --timezone Europe/London --transport resend
$EB add-user alice --deployment ~/repos/acme-email-batches --name "Alice"
$EB add-recipient acme --deployment ~/repos/acme-email-batches --to ceo@acme.test --cadence daily --at 17:00 --days mon,tue,wed,thu,fri
$EB configure-client --deployment ~/repos/acme-email-batches --user alice
$EB queue acme --subject "DNS cutover done" --topic Website --body "Finished at 14:00."
$EB queue acme --subject "Site down" --body "Investigating." --urgent
$EB status -v
$EB preview acme
$EB tick            # what the server runs
```

## Prior art

This plugin builds on [Client-Update-Pipeline-Notes](https://github.com/danielrosehill/Client-Update-Pipeline-Notes) and [Agent-Briefing-Gateway](https://github.com/danielrosehill/Agent-Briefing-Gateway).

## License

MIT
