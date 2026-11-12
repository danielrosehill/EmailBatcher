# EmailBatcher

A Claude Code plugin for outbound email batching. Instead of sending each update to a recipient as it happens, messages are held in an outbound queue and released as one consolidated email when a threshold is reached (count, age, or schedule). An override rule lets a genuinely urgent message go out immediately.

Status: **design stage.** No skills yet. See [docs/design.md](docs/design.md).

## The problem

Someone who works with clients (or any frequent correspondent) produces a stream of small updates. Sending each one as its own email floods the recipient's inbox; holding them back by hand means remembering to send. EmailBatcher sits between the sender and the recipient and does the holding and consolidating.

## Prior art (same author)

- [Client-Update-Pipeline-Notes](https://github.com/danielrosehill/Client-Update-Pipeline-Notes): the original sketch (2025-11-18). Per-client alias address, Google Group as the catcher, an agent summarises the queue into one email per period.
- [Agent-Briefing-Gateway](https://github.com/danielrosehill/Agent-Briefing-Gateway): the same staging-and-batching mechanism pointed inbound (sub-agents to a human), with a budgeted override channel (2026-07-30).

## Installation

```bash
claude plugins install email-batcher@danielrosehill
```

(Not yet registered in the marketplace.)

## License

MIT
