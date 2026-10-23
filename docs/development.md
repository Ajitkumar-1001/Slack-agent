# Development guide

How to work on the FlowPilot backend: set it up, run the checks, and validate each integration.
For the end-to-end Slack demo, see [`runbook.md`](runbook.md). That live run **has not happened
yet**, so treat anything below marked "manual" as unverified until someone does it.

## Toolchain

- Python **3.12** with **[uv](https://docs.astral.sh/uv/)**. Every command runs from `backend/` as
  `uv run …`. Add dependencies with `uv add` and commit the updated `uv.lock`. Don't use pip,
  Poetry or Conda.
- PostgreSQL is the system of record. For local work, `docker compose up -d db` (from the repo
  root) starts one on `127.0.0.1:5432`. The matching `DATABASE_URL` is in the header comment of
  `docker-compose.yml`.

```bash
cd backend
uv sync                         # install runtime + dev dependencies from uv.lock
uv run alembic upgrade head     # create/upgrade the schema (needs DATABASE_URL)
uv run uvicorn app.main:app --reload
```

Configuration is a Pydantic `Settings` class (`app/config.py`). Each field reads the upper-cased
environment variable, or a `.env` file in the working directory. `backend/.env.example` is the
template. The README lists every variable and which ones are required.

## Rules the code relies on

These are deliberate, and tests check most of them. Keep them intact when changing code:

- **Slack is the only UI.** There's no web frontend. Users interact through @mentions, DMs, and
  Block Kit cards and buttons.
- **No external write without a recorded approval.** `workflows/execute_plan.py` refuses to run
  unless the proposal is `proposal_approved`, and `approve_plan` persists the decision first.
  Reject must create nothing.
- **Every write is idempotent through the database.** Each (task, target system) action gets a
  deterministic key in `action_logs.idempotency_key`. Adapters check the local record first, then
  look for an existing remote item carrying the key, and only then create. Never keep this state
  only in memory.
- **LLM output is validated, not parsed best-effort.** The planner validates against `ProjectPlan`.
  On failure it retries once, then raises, and nothing is saved.
- **Raw Slack and Drive content is never stored or indexed.** Retrieved context lives only for the
  current plan. Logs record counts and error types, never message bodies.
- **External systems stay behind `tools/`.** Each adapter exposes small injectable functions
  (`create_remote`, `search_remote`, …) so tests can swap them out without network access.
  Transient HTTP errors go through `tools/retry.py`.
- **Secrets come from the environment only.** Never hardcode or log them.

## Quality gate

Run all four before calling a change done. If something fails, note whether the failure is new or
was already there.

```bash
uv run ruff check .
uv run ruff format --check .    # `uv run ruff format .` to fix
uv run mypy .
uv run pytest -q
```

Coverage runs automatically with `uv run pytest`. `pytest-cov` is a dev dependency, and the
`[tool.pytest.ini_options]` `addopts` in `backend/pyproject.toml` reports per-file coverage
with missing lines for `app`, `slack`, `agents`, `workflows`, `tools` and `db`. There's no
`--cov-fail-under`, so low coverage never fails the run. Pass `--no-cov` to skip it.

`pre-commit` is in the dev dependencies, but no hook config is committed yet, and there's no CI
workflow either. The gate above is run by hand for now.

### What the tests cover

The suite runs offline against in-memory SQLite (`tests/conftest.py` sets dummy env vars), with
every external call injected or monkeypatched.

| Test file | Covers |
|---|---|
| `test_schemas.py` | `ProjectPlan` and related Pydantic validation |
| `test_planner.py` | planner retry/safe-fail and prompt construction (including untrusted-text fencing) |
| `test_events.py` | planning-intent gate, routing, suggested-prompt reply |
| `test_retrieval.py` | Slack context retrieval: event-payload default, RTS path, fallback on errors |
| `test_google_drive_retrieval.py` | Drive adapter: search/export, folder scoping, never raises on failure |
| `test_blocks.py` | approval card and stakeholder summary Block Kit payloads |
| `test_transitions.py` | approval state machine, authorization, first-decision-wins |
| `test_workflows.py` | create/approve/execute workflows end to end with fakes, including Drive on/off/failing |
| `test_idempotency.py` | duplicate approvals and retries create no duplicate writes |
| `test_github_payloads.py`, `test_jira_payloads.py`, `test_notion_payloads.py` | adapter payloads and idempotent create |
| `test_retry.py` | backoff, `Retry-After`, which errors are retried |
| `test_slack_signature.py` | Bolt signature verification and URL verification |
| `test_health.py` | `/health` with the database up and down |
| `test_docker.py` | static checks on the Dockerfile, `.dockerignore` and compose file |
| `test_slack_manifest.py` | manifest and docs stay in step with the code |

Run one file or one test with `uv run pytest tests/test_blocks.py` or
`uv run pytest tests/test_blocks.py::test_name`.

## Database migrations

Models live in `db/models.py` and migrations in `db/migrations/versions/`. After changing a model,
add a new revision. Don't edit an applied one.

```bash
uv run alembic revision -m "describe the change"   # then fill in upgrade()/downgrade()
uv run alembic upgrade head
```

## Validating each piece

Each item gives the automated check first, then the manual one. Manual checks need real
credentials and a running server (see the runbook for Slack app setup and ngrok).

### Health check

```bash
uv run pytest tests/test_health.py
```

Manual: with the server running, `curl localhost:8000/health` should return
`{"status":"ok","db":"ok"}`. Stop Postgres and it should return `"db":"unreachable"` within about
two seconds, still with HTTP 200.

### GitHub (default target)

Automated: `test_github_payloads.py`, `test_idempotency.py`, `test_workflows.py`.

Manual: point `GITHUB_OWNER`/`GITHUB_REPO` at a throwaway repo and approve a plan. Each task should
become one issue. Clicking Approve again shows "already decided" and creates nothing new.

### Jira (optional)

Automated: `test_jira_payloads.py`.

Manual: set `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` and `JIRA_PROJECT_KEY`, pick **Jira**
or **Both** on the card, and approve. With **Both**, each task gets its own GitHub issue and Jira
ticket, and the summary lists each system separately.

### Notion project brief (optional)

Automated: `test_notion_payloads.py`, `test_blocks.py`.

Manual: set `NOTION_API_KEY` and `NOTION_PARENT_PAGE_ID`, and give the Notion integration access to
that parent page. The card then shows a "Generate Notion project brief" checkbox
(`DEFAULT_NOTION_ENABLED=true` pre-ticks it). Approving creates one brief page linking the created
issues/tickets. If the brief fails, the summary says so explicitly and the GitHub/Jira results are
unaffected.

### Google Drive context (optional, read-only)

Automated:

```bash
uv run pytest tests/test_google_drive_retrieval.py
uv run pytest tests/test_workflows.py -k drive
```

These check three things. The adapter returns documents when the injected calls succeed. It
returns an empty "unavailable" result instead of raising on any failure. And when Drive is disabled
or unconfigured, it is never called at all.

Manual setup, once, outside this repo:

1. Create a Google Cloud service account and enable the Drive API on its project.
2. Download its JSON key, and share the Drive folder you want searched with the service account's
   email address. No Workspace admin step or domain-wide delegation is needed.
3. Set `GOOGLE_DRIVE_CREDENTIALS` to the JSON key **content** (not a path), optionally
   `GOOGLE_DRIVE_FOLDER_SCOPE` to the folder ID, and `DEFAULT_GOOGLE_DRIVE_ENABLED=true`.

Then post a planning request whose topic matches a Google Doc/Sheet/Slides file in that folder.
You should see a "Searching relevant Google Drive context…" progress message, and the stored plan's
`evidence_summary` should reference the document. The card isn't rendered from it, so check the
`project_proposals.plan_json` column. Approval and execution behave exactly as without Drive, and
no audit row is written for the read. Two more checks: with the flag off, planning runs on Slack
context only; with the credentials deliberately broken, planning still succeeds and Slack shows no
error.

### Slack Real-Time Search (optional, off by default)

Automated: `test_retrieval.py`.

Manual: needs a workspace where Real-Time Search is available, the RTS scopes uncommented in
`docs/slack-app-manifest.yaml` (then reinstall the app), and `SLACK_RTS_ENABLED=true`. The RTS
response parsing follows Slack's public docs and hasn't been checked against a live call. If a
`slack_rts_unavailable` warning shows up in the logs, the request fell back to the triggering
message.

### Docker image

```bash
uv run pytest tests/test_docker.py
docker build -f backend/Dockerfile -t flowpilot-ai-backend backend    # from the repo root
docker run -p 8000:8000 --env-file backend/.env flowpilot-ai-backend
curl localhost:8000/health
```

The build should succeed without any secrets. On start the container runs
`alembic upgrade head` and only then serves. A missing setting or an unreachable database makes it
exit instead of serving half-configured. `docker history flowpilot-ai-backend` should show no
credential values in any layer.
