"""Notion project-brief adapter (003-flowpilot-notion-integration; FR-201-206; ADR-004).

Mirrors tools/github.py's/tools/jira.py's injected-IO idempotency shape exactly (research.md
Decision 4 — IssueOutcome/RemoteLookup/RemoteCreate are reused as-is, not duplicated), but is
called once per proposal instead of once per task. The idempotency marker lives in the created
page's title, not a body comment or label (research.md Decision 2 — the parent is a plain page,
not a database, so there are no custom properties to tag, and Notion's search endpoint indexes
titles only).
"""
from app.config import settings
from db.models import ActionLogStatus
from tools.github import IssueOutcome, RemoteCreate, RemoteLookup
from tools.retry import send_with_retry

import httpx

from agents.schemas import ProjectPlan

_NOTION_API = "https://api.notion.com/v1"
_SYSTEM_ORDER = ("github", "jira")


def _rich_text(content: str) -> list[dict]:
    return [{"type": "text", "text": {"content": content}}]


def _heading_2(content: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text(content)}}


def _paragraph(content: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(content)}}


def _bullet(content: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(content)},
    }


def _bullet_link(content: str, url: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": content, "link": {"url": url}}}]
        },
    }


def build_brief_payload(
    proposal_id: str, plan: ProjectPlan, links: list[tuple[str, str, str]], idempotency_key: str
) -> dict:
    """Build a Notion ``POST /v1/pages`` payload summarizing the whole proposal — objective,
    timeline, milestones, tasks, risks, and a "Tracked work" section linking every GitHub/Jira
    artifact already created for this proposal (GitHub before Jira, per data-model.md)."""
    title_text = f"{plan.project_name} — Project Brief [{idempotency_key}]"

    children: list[dict] = [
        _heading_2("Objective"),
        _paragraph(plan.objective),
        _paragraph(f"Timeline: {plan.timeline or 'not specified'}"),
        _heading_2("Milestones"),
    ]
    for milestone in plan.milestones:
        children.append(
            _bullet(
                f"{milestone.title} — due {milestone.due_date or 'not specified'} — "
                f"{'; '.join(milestone.success_criteria) or 'no success criteria'}"
            )
        )

    children.append(_heading_2("Tasks"))
    for task in plan.tasks:
        children.append(
            _bullet(f"{task.title} — {task.suggested_owner or 'unassigned'} — priority: {task.priority}")
        )

    children.append(_heading_2("Risks"))
    for risk in plan.risks:
        children.append(_bullet(f"{risk.title} ({risk.severity}) — {risk.mitigation}"))

    children.append(_heading_2("Tracked work"))
    ordered_links = sorted(
        links, key=lambda link: _SYSTEM_ORDER.index(link[0]) if link[0] in _SYSTEM_ORDER else len(_SYSTEM_ORDER)
    )
    for _system, link_title, url in ordered_links:
        children.append(_bullet_link(link_title, url))

    return {
        "parent": {"page_id": settings.notion_parent_page_id},
        "properties": {"title": {"title": _rich_text(title_text)}},
        "children": children,
    }


async def create_brief_idempotent(
    *,
    idempotency_key: str,
    payload: dict,
    find_local: RemoteLookup,
    search_remote: RemoteLookup,
    create_remote: RemoteCreate,
) -> IssueOutcome:
    """Create one project brief, never a duplicate — identical 3-step shape to
    create_issue_idempotent/create_ticket_idempotent:
    1. a durable local record for this key -> SKIPPED_DUPLICATE (duplicate click / retry);
    2. else an existing Notion page whose title already carries this key -> SKIPPED_DUPLICATE
       (reconciles a write that succeeded but whose local record was lost before persisting);
    3. else create it -> SUCCEEDED. The idempotency marker is already baked into ``payload``'s
       title by build_brief_payload, so no re-marking step is needed here (unlike GitHub/Jira).
    """
    local = await find_local(idempotency_key)
    if local is not None:
        return IssueOutcome(ActionLogStatus.SKIPPED_DUPLICATE, local[0], local[1])

    remote = await search_remote(idempotency_key)
    if remote is not None:
        return IssueOutcome(ActionLogStatus.SKIPPED_DUPLICATE, remote[0], remote[1])

    external_id, external_url = await create_remote(payload)
    return IssueOutcome(ActionLogStatus.SUCCEEDED, external_id, external_url)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.notion_api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


async def notion_create_page(payload: dict) -> tuple[str, str]:
    """Real Notion REST create — POST /v1/pages."""
    async with httpx.AsyncClient(timeout=30) as client:
        # ponytail: no 5xx resend — same reason as github_create_issue (no request idempotency key,
        # index-lagged search); a 5xx'd create is recorded FAILED and reconciled on re-run instead.
        resp = await send_with_retry(
            lambda: client.post(
                f"{_NOTION_API}/pages", headers=_headers(), json=payload
            ),
            retry_5xx=False,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"], data["url"]


async def notion_find_page(idempotency_key: str) -> tuple[str, str] | None:
    """Real Notion REST reconciliation — POST /v1/search, filtered client-side for a page whose
    title contains the exact idempotency marker (research.md Decision 2)."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Read-only despite POST, so 5xx is safe to resend.
        resp = await send_with_retry(
            lambda: client.post(
                f"{_NOTION_API}/search",
                headers=_headers(),
                json={
                    "query": idempotency_key,
                    "filter": {"property": "object", "value": "page"},
                },
            ),
            retry_5xx=True,
        )
        resp.raise_for_status()
        for page in resp.json().get("results", []):
            title_parts = page.get("properties", {}).get("title", {}).get("title", [])
            title_text = "".join(part.get("plain_text", "") for part in title_parts)
            if idempotency_key in title_text:
                return page["id"], page["url"]
        return None
