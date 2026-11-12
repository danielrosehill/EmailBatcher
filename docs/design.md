# Design

Placeholder: to be filled from the author's design brief.

## Open questions

- **Queue storage.** Local markdown/JSON files in the user's data directory, or a server-side consolidator (middleware) so queued messages survive across machines and sessions and a release can fire without a Claude session open.
- **Release triggers.** Count threshold, oldest-message age, fixed schedule, or a combination per recipient.
- **Override rule.** What marks a message as urgent, and whether urgent sends flush the queue with them.
- **Consolidation.** Concatenate, or summarise into an executive-summary email.
- **Send route.** Which mail tool delivers the batched message.
