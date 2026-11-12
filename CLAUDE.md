# EmailBatcher (plugin repo)

Public Claude Code plugin, manifest name `email-batcher`, repo `danielrosehill/EmailBatcher`. Read `docs/design.md` before changing behaviour.

- All logic lives in `scripts/emailbatcher.py` (stdlib only, JSON out). Skills only tell the agent which subcommand to run. Keep it that way.
- When you change the script, bump `VERSION` in it and `version` in `.claude-plugin/plugin.json` together. Existing deployments carry their own copy in `bin/`, so the `setup-server` skill documents the upgrade.
- Test with the `file` transport in a temp dir: init, add-user, add-recipient, queue, status, preview, tick, release. For the multi-user path, use a bare repo as the remote. See the test notes in `docs/design.md`.
- Keep the plugin generic: no personal hosts, addresses or infra in skills or docs.
- Skill `description` frontmatter must be 140 characters or fewer.
