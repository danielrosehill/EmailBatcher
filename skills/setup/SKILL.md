---
name: setup
description: Onboard to EmailBatcher - create a team outbound email queue deployment or join one; writes the user profile and client config.
---

# EmailBatcher setup and onboarding

Two paths. Ask which one applies if it is not obvious:

- **New deployment**: first person on a team (or a solo user) creating the shared queue.
- **Join**: a team member whose admin already created the deployment repo.

## The CLI

All work goes through `emailbatcher.py` (stdlib Python, JSON on stdout). Call it as `$EB` below:

- Once a deployment exists, use the copy inside it: `python3 <deployment>/bin/emailbatcher.py`.
- Before that (setup), use `${CLAUDE_PLUGIN_ROOT}/scripts/emailbatcher.py`, or fetch `https://raw.githubusercontent.com/danielrosehill/EmailBatcher/main/scripts/emailbatcher.py` if the plugin is not installed locally.

The workstation client config (deployment path + who this user is) lives at
`${CLAUDE_USER_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-plugins}/email-batcher/config.json`.
If it is missing, run the `setup` skill first.

## Data storage

- The **deployment** is user-owned data: a directory (normally a **private** git repo) holding `emailbatcher.json`, `users/`, `recipients/`, `queue/`, `sent/`, `state/` and `bin/emailbatcher.py`. Suggest `~/repos/<team>-email-batches`. It holds client correspondence: never make the remote public.
- The only thing written under `${WORKSPACE:email-batcher}` is `config.json` (pointer to the deployment + this user's id).

## Steps: new deployment

1. Gather, asking only for what is missing: team/deployment name; the **agreed sender** address and display name all batched mail goes out from; timezone (IANA, e.g. `Asia/Jerusalem`); transport (`resend`, `smtp` + host/port, or `file` for a dry run that writes .eml files to `outbox/`).
2. `$EB init <path> --name ... --sender-email ... --sender-name ... --timezone ... --transport ...`
3. Create a **private** GitHub repo and push the deployment (`gh repo create <owner>/<name> --private --source=<path> --push`). Skip only for a deliberately local, single-machine setup; then say releases only happen when this machine runs `tick`.
4. Add the user's own profile with the `manage-team` skill (id = short lowercase handle).
5. Add the first recipient with the `manage-recipients` skill (cadence, addresses).
6. `$EB configure-client --deployment <path> --user <id>`
7. Recommend server-side release (the `setup-server` skill) so batches go out while workstations are off. Until then, releases happen only on `release-batch` or a local `tick`.

## Steps: join an existing deployment

1. Get the deployment repo URL from the team admin; clone it (suggest `~/repos/<name>`).
2. If `users/<id>.json` is not there for this person, add it (`manage-team`).
3. `$EB configure-client --deployment <clone path> --user <id>`
4. `$EB status` to confirm the recipients are visible.

## Notes

- Transport secrets never go into the deployment repo. They are environment variables on the machine that sends: `EMAILBATCHER_RESEND_API_KEY`, or `EMAILBATCHER_SMTP_USER` / `EMAILBATCHER_SMTP_PASSWORD`.
- Re-running `configure-client` switches this workstation to another deployment or identity.
