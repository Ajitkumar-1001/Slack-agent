"""Jira Cloud ticket adapter (002-flowpilot-jira-integration; FR-102/FR-104).

Mirrors tools/github.py's injected-IO idempotency shape exactly (research.md Decision 7 —
IssueOutcome/RemoteLookup/RemoteCreate are reused as-is, not duplicated). The one adapter-specific
difference: the idempotency marker is attached as a label (Jira descriptions are Atlassian
Document Format, not plain markdown, and free-text ADF search is index-lag-prone — a label gives
an exact-match JQL lookup instead; research.md Decision 4).
"""
from agents.schemas import Task
from app.config import settings
from db.models import ActionLogStatus
from tools.github import IssueOutcome, RemoteCreate, RemoteLookup
from tools.retry import send_with_retry

import httpx

_REQUIRED_LABELS = ["flowpilot", "approved", "ai-generated", "mvp"]
_PRIORITY_MAP = {"low": "Low", "medium": "Medium", "high": "High"}


def _marker_label(idempotency_key: str) -> str:
    return f"flowpilot-key-{idempotency_key}"


def build_ticket_payload(task: Task) -> dict:
    body_lines = [task.description, "", "## Acceptance criteria"]
    body_lines += [f"- {c}" for c in task.acceptance_criteria] or ["- (none specified)"]
    return {
        "fields": {
            "project": {"key": settings.jira_project_key},
            "summary": task.title,
            "description": "\n".join(body_lines),
            "issuetype": {"name": "Task"},
            "priority": {"name": _PRIORITY_MAP[task.priority]},
            "labels": list(_REQUIRED_LABELS),
        }
    }


async def create_ticket_idempotent(
    *,
    idempotency_key: str,
    payload: dict,
    find_local: RemoteLookup,
    search_remote: RemoteLookup,
    create_remote: RemoteCreate,
) -> IssueOutcome:
    """Create one ticket, never a duplicate — identical 3-step shape to create_issue_idempotent:
    1. a durable local record for this key -> SKIPPED_DUPLICATE (duplicate click / retry);
    2. else an existing Jira ticket tagged with this key's marker label -> SKIPPED_DUPLICATE
       (reconciles a write that succeeded but whose local record was lost before persisting);
    3. else create it -> SUCCEEDED.
    """
    local = await find_local(idempotency_key)
    if local is not None:
        return IssueOutcome(ActionLogStatus.SKIPPED_DUPLICATE, local[0], local[1])

    remote = await search_remote(idempotency_key)
    if remote is not None:
        return IssueOutcome(ActionLogStatus.SKIPPED_DUPLICATE, remote[0], remote[1])

    fields = payload.get("fields", {})
    marked = {
        **payload,
        "fields": {**fields, "labels": [*fields.get("labels", []), _marker_label(idempotency_key)]},
    }
    external_id, external_url = await create_remote(marked)
    return IssueOutcome(ActionLogStatus.SUCCEEDED, external_id, external_url)


def _auth() -> tuple[str, str]:
    return (settings.jira_email or "", settings.jira_api_token or "")


async def jira_create_ticket(payload: dict) -> tuple[str, str]:
    """Real Jira Cloud REST v3 create — POST /rest/api/3/issue."""
    async with httpx.AsyncClient(timeout=30) as client:
        # ponytail: no 5xx resend — same reason as github_create_issue (no request idempotency key,
        # index-lagged JQL); a 5xx'd create is recorded FAILED and reconciled on re-run instead.
        resp = await send_with_retry(
            lambda: client.post(
                f"{settings.jira_base_url}/rest/api/3/issue",
                auth=_auth(),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=payload,
            ),
            retry_5xx=False,
        )
        resp.raise_for_status()
        key = resp.json()["key"]
        return key, f"{settings.jira_base_url}/browse/{key}"


async def jira_find_ticket(idempotency_key: str) -> tuple[str, str] | None:
    """Real Jira Cloud REST v3 reconciliation lookup — JQL search for the marker label."""
    jql = f'project = "{settings.jira_project_key}" AND labels = "{_marker_label(idempotency_key)}"'
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await send_with_retry(
            lambda: client.get(
                f"{settings.jira_base_url}/rest/api/3/search",
                auth=_auth(),
                headers={"Accept": "application/json"},
                params={"jql": jql},
            ),
            retry_5xx=True,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
        if issues:
            key = issues[0]["key"]
            return key, f"{settings.jira_base_url}/browse/{key}"
        return None
