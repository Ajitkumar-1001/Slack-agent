"""GitHub issue adapter (Constitution X/XI/XII; ADR-004). Idempotent, audited external writes.

The idempotency orchestration (`create_issue_idempotent`) is pure over three injected IO
callables so it is fully testable offline; the real GitHub REST calls are the defaults used
in production.
"""
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from agents.schemas import Task
from app.config import settings
from db.models import ActionLogStatus

_REQUIRED_LABELS = ["flowpilot", "approved", "ai-generated", "mvp"]
_GITHUB_API = "https://api.github.com"

# find_local(key) / find_remote(key) -> (external_id, external_url) | None ; create(payload) -> (id, url)
RemoteLookup = Callable[[str], Awaitable[tuple[str, str] | None]]
RemoteCreate = Callable[[dict], Awaitable[tuple[str, str]]]


@dataclass
class IssueOutcome:
    status: ActionLogStatus
    external_id: str | None
    external_url: str | None
    error: str | None = None


def compute_idempotency_key(proposal_id: str, task: Task) -> str:
    """Deterministic per (proposal, task) — the same approved task always maps to the same key."""
    raw = f"{proposal_id}\x00{task.title}\x00{task.description}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_issue_payload(task: Task) -> dict:
    body_lines = [task.description, "", "## Acceptance criteria"]
    body_lines += [f"- {c}" for c in task.acceptance_criteria] or ["- (none specified)"]
    return {"title": task.title, "body": "\n".join(body_lines), "labels": list(_REQUIRED_LABELS)}


async def create_issue_idempotent(
    *,
    idempotency_key: str,
    payload: dict,
    find_local: RemoteLookup,
    search_remote: RemoteLookup,
    create_remote: RemoteCreate,
) -> IssueOutcome:
    """Create one issue, never a duplicate:
    1. a durable local record for this key -> SKIPPED_DUPLICATE (duplicate click / retry);
    2. else an existing GitHub issue tagged with this key -> SKIPPED_DUPLICATE
       (reconciles a write that succeeded but whose local record was lost before persisting);
    3. else create it -> SUCCEEDED.
    """
    local = await find_local(idempotency_key)
    if local is not None:
        return IssueOutcome(ActionLogStatus.SKIPPED_DUPLICATE, local[0], local[1])

    remote = await search_remote(idempotency_key)
    if remote is not None:
        return IssueOutcome(ActionLogStatus.SKIPPED_DUPLICATE, remote[0], remote[1])

    marked = {**payload, "body": payload.get("body", "") + f"\n\n<!-- flowpilot-key:{idempotency_key} -->"}
    external_id, external_url = await create_remote(marked)
    return IssueOutcome(ActionLogStatus.SUCCEEDED, external_id, external_url)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def github_create_issue(payload: dict) -> tuple[str, str]:
    """Real GitHub REST create — POST /repos/{owner}/{repo}/issues."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_GITHUB_API}/repos/{settings.github_owner}/{settings.github_repo}/issues",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["number"]), data["html_url"]


async def github_find_issue(idempotency_key: str) -> tuple[str, str] | None:
    """Real GitHub REST reconciliation lookup — search issues carrying this key marker in the body."""
    query = (
        f"repo:{settings.github_owner}/{settings.github_repo} "
        f'in:body "flowpilot-key:{idempotency_key}"'
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{_GITHUB_API}/search/issues", headers=_headers(), params={"q": query}
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            return str(items[0]["number"]), items[0]["html_url"]
        return None
