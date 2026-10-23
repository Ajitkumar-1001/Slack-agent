# FlowPilot demo runbook

> **Status: the live demo (T043) has NOT been run.** No one has run this runbook yet against a
> real Slack workspace with real credentials. Every step comes from the code and from
> `.specify/specs/001-flowpilot-slack-mvp/quickstart.md` Phase 7. If a step turns out wrong on a
> live run, fix this file.

Flow being demoed: Slack request → plan → Block Kit approval card → Approve → GitHub issues →
audit rows → Slack stakeholder summary.

## Prerequisites

- A Slack workspace where you're allowed to install apps.
- Python 3.12 and [`uv`](https://docs.astral.sh/uv/). Don't use pip, Poetry or Conda.
- Postgres: Docker (for the repo's `docker-compose.yml`) or a Supabase/Postgres instance.
- [ngrok](https://ngrok.com/) or another public HTTPS tunnel to localhost.
- An Anthropic API key.
- A GitHub token that can create issues in a **throwaway** test repo. The demo creates real issues.

## 1. Create the Slack app from the manifest

1. Go to api.slack.com/apps → **Create New App** → **From a manifest**, then pick the workspace.
2. Paste [`docs/slack-app-manifest.yaml`](slack-app-manifest.yaml) and create the app.
   The `YOUR-HOST` request URLs are placeholders. Slack can't verify them yet, which is
   expected; you set the real URLs in step 6. If Slack won't create the app with unverifiable
   URLs, delete both `request_url` lines, create the app, and add the URLs in step 6.
3. **Basic Information → App Credentials**: copy the **Signing Secret** into `SLACK_SIGNING_SECRET`.
4. **Install App → Install to Workspace**: copy the **Bot User OAuth Token** into
   `SLACK_BOT_TOKEN`.

The manifest subscribes to `app_mention` and `message.im` only, because those are the only
events `backend/slack/events.py` handles. The Assistant panel (`assistant_thread_started`) has
**no handler**, so it isn't enabled. Use an @mention or a DM.

## 2. Configure environment variables

Copy `backend/.env.example` to `backend/.env` (gitignored) or export the variables in your
shell. Settings are read by `backend/app/config.py`, and env var names match the field names in
upper case. Never commit or log these values.

Required (the app won't start without them):

| Variable | Notes |
|---|---|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token from step 1.4 |
| `SLACK_SIGNING_SECRET` | from step 1.3 |
| `ANTHROPIC_API_KEY` | |
| `DATABASE_URL` | must use the `postgresql+asyncpg://` scheme |
| `GITHUB_TOKEN` | needs issue write access to the repo below |
| `GITHUB_OWNER` | user or org that owns the demo repo |
| `GITHUB_REPO` | demo repo name |

Optional (defaults are fine for the demo):

| Variable | Default | Effect |
|---|---|---|
| `DEFAULT_MODEL_PROVIDER` / `DEFAULT_MODEL_NAME` | `anthropic` / `claude-sonnet-5` | planner model |
| `FLOWPILOT_APPROVER_IDS` | empty | comma-separated Slack user IDs that may decide on any plan; the requester always can |
| `SLACK_RTS_ENABLED` | `false` | live Real-time Search. Leave off: grounding then uses only the triggering message (ADR-005). Turning it on also needs the RTS scopes commented out in the manifest |
| `DEFAULT_TARGET_SYSTEM` | `github` | `github` \| `jira` \| `both` |
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` | unset | Jira target (optional) |
| `NOTION_API_KEY`, `NOTION_PARENT_PAGE_ID`, `DEFAULT_NOTION_ENABLED` | unset / `false` | Notion project brief (optional) |
| `GOOGLE_DRIVE_CREDENTIALS`, `GOOGLE_DRIVE_FOLDER_SCOPE`, `DEFAULT_GOOGLE_DRIVE_ENABLED` | unset / `false` | Drive grounding (optional) |
| `LOG_LEVEL` | `INFO` | |

## 3. Install, database and migrations

```bash
docker compose up -d db          # from the repo root; skip if using Supabase/your own Postgres
cd backend
uv sync
uv run alembic upgrade head      # creates project_proposals, approval_decisions, action_logs, external_artifacts
```

For the compose database, `DATABASE_URL` is the URL in the header comment of
`docker-compose.yml`.

## 4. Run the API

```bash
cd backend
uv run uvicorn app.main:app --reload   # serves on localhost:8000
curl -s localhost:8000/health          # expect {"status":"ok","db":"ok"}
```

Don't move on until `db` is `ok`.

## 5. Open the tunnel

```bash
ngrok http 8000
```

Note the `https://…` forwarding host. Free ngrok hosts change on every restart, so redo step 6
each time you restart ngrok.

## 6. Point Slack at the tunnel

The server from step 4 **must already be running**. Slack sends a signed URL-verification
challenge, and Bolt only answers it if `SLACK_SIGNING_SECRET` is correct.

1. **Event Subscriptions → Request URL**: `https://<ngrok-host>/slack/events`. Wait for
   **Verified**, then save.
2. **Interactivity & Shortcuts → Request URL**: `https://<ngrok-host>/slack/actions`, then save.

You can also go to **App Manifest**, replace `YOUR-HOST` with the ngrok host, and save.

## 7. Demo script (`#flowpilot-demo`)

Setup: create `#flowpilot-demo` and run `/invite @FlowPilot` in it.

1. Post: `@FlowPilot launch our customer onboarding redesign in four weeks.`
2. Expect an immediate "Got it — I'll turn this into an execution plan…" plus progress messages
   ("Searching relevant Slack context…", "Drafting execution plan…"), then the approval card
   (milestones / tasks / risks, a target-system selector, and **Approve** / **Edit Plan** /
   **Reject**) within 30 s.
3. Click **Approve**. Expect a stakeholder summary listing the created GitHub issues with links.
   Open the repo and confirm the issues exist.
4. Check the audit trail in Postgres:
   ```sql
   SELECT status FROM project_proposals ORDER BY created_at DESC LIMIT 1;
   SELECT * FROM approval_decisions;
   SELECT target_system, status, idempotency_key FROM action_logs;
   SELECT * FROM external_artifacts;
   ```
5. Click **Approve** on the same card again. Expect an ephemeral "already decided" notice and
   **no** new issues in the repo.
6. Post a second request, then click **Reject** on the new card. Expect "Plan rejected — no
   issues were created." and no new `action_logs` / `external_artifacts` rows.
7. Optional: DM FlowPilot the same request (no @mention needed) to show the DM entry point.

Success moment (SC-001): one Slack request becomes a plan, an approval card, GitHub issues and a
stakeholder update, all without leaving Slack.

After a real run, record the outcome in T043 in `.specify/specs/001-flowpilot-slack-mvp/tasks.md`.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| App won't start: pydantic `ValidationError` | a required env var from step 2 is missing |
| `/health` shows `"db":"unreachable"` | DB not running, wrong host/credentials, or `DATABASE_URL` not using `postgresql+asyncpg://` |
| Slack won't verify the Request URL | server or tunnel not running; path isn't exactly `/slack/events`; wrong `SLACK_SIGNING_SECRET` (Bolt rejects bad signatures before any handler); ngrok host changed |
| No reply to an @mention | bot not invited to the channel; Event Subscriptions not saved; scopes changed without reinstalling the app |
| Can't DM the bot | App Home **Messages Tab** is off. The manifest turns it on; reinstall if you changed it |
| Bot replies with suggested prompts instead of a plan | the message failed the planning-intent gate; use a planning phrase such as "create an execution plan for …" |
| "Sorry, I couldn't draft an execution plan…" | the planner call or validation failed; check `ANTHROPIC_API_KEY` / `DEFAULT_MODEL_NAME` and the `plan_generation_failed` log line. Nothing was saved |
| Buttons do nothing or show a Slack error | Interactivity Request URL is wrong or not saved (`/slack/actions`) |
| "You're not allowed to act on this plan" | only the requester or a user in `FLOWPILOT_APPROVER_IDS` can decide |
| Summary lists failed tasks | GitHub token lacks issue write access on `GITHUB_OWNER/GITHUB_REPO`. Fix the token, then post a fresh request. Re-clicking Approve on a decided card only shows "already decided" |
| `slack_rts_unavailable` warning in logs | `SLACK_RTS_ENABLED=true` but the RTS call failed; it falls back to the triggering message. Leave RTS off for the demo |
| Assistant panel shows nothing | not supported: no `assistant_thread_started` handler exists |
