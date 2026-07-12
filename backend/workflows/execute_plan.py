"""Execute an approved plan: one idempotent GitHub issue and/or Jira ticket per (task, target
system), audited, partial-failure aware.

Guarded so no external write happens unless the proposal is approved (Constitution X). Idempotency
is durable in the DB (ActionLog keyed by a deterministic idempotency key) so retries, duplicate
approvals, or a crash between the write and its local record never create duplicates.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.schemas import ProjectPlan, Task
from db.models import ActionLog, ActionLogStatus, ExternalArtifact, ProjectProposal, ProposalStatus
from db.repository import ActionLogRepository, ExternalArtifactRepository
from tools.github import (
    IssueOutcome,
    RemoteCreate,
    RemoteLookup,
    build_issue_payload,
    compute_idempotency_key,
    create_issue_idempotent,
    github_create_issue,
    github_find_issue,
)
from tools.jira import build_ticket_payload, create_ticket_idempotent, jira_create_ticket, jira_find_ticket

log = structlog.get_logger()


class ExecutionNotApprovedError(Exception):
    pass


@dataclass(frozen=True)
class _Adapter:
    build_payload: Callable[[Task], dict]
    create_idempotent: Callable[..., Awaitable[IssueOutcome]]
    action_type: str
    artifact_type: str


_ADAPTERS = {
    "github": _Adapter(build_issue_payload, create_issue_idempotent, "create_github_issue", "issue"),
    "jira": _Adapter(build_ticket_payload, create_ticket_idempotent, "create_jira_ticket", "ticket"),
}


def _resolve_target_systems(target_systems: list[str] | None) -> list[str]:
    """None -> v1's GitHub-only default (AC-105); "both" expands to ["github", "jira"] so
    every (task, system) pair gets its own idempotency key (research.md Decision 3/6)."""
    if target_systems is None:
        return ["github"]
    resolved: list[str] = []
    for system in target_systems:
        resolved.extend(["github", "jira"] if system == "both" else [system])
    return resolved


async def execute_plan(
    *,
    session: AsyncSession,
    proposal: ProjectProposal,
    target_systems: list[str] | None = None,
    create_remote: RemoteCreate = github_create_issue,
    search_remote: RemoteLookup = github_find_issue,
    jira_create_remote: RemoteCreate = jira_create_ticket,
    jira_search_remote: RemoteLookup = jira_find_ticket,
) -> list[tuple[Task, str, IssueOutcome]]:
    if proposal.status != ProposalStatus.APPROVED:
        raise ExecutionNotApprovedError(
            f"proposal {proposal.id} is not approved (status={proposal.status})"
        )

    proposal.status = ProposalStatus.EXECUTING
    await session.flush()

    plan = ProjectPlan(**proposal.plan_json)
    action_repo = ActionLogRepository(session)
    artifact_repo = ExternalArtifactRepository(session)
    remotes = {"github": (create_remote, search_remote), "jira": (jira_create_remote, jira_search_remote)}
    resolved_systems = _resolve_target_systems(target_systems)

    async def find_local(key: str) -> tuple[str, str] | None:
        existing = await action_repo.get_by_idempotency_key(key)
        if existing is None or existing.status not in (
            ActionLogStatus.SUCCEEDED,
            ActionLogStatus.SKIPPED_DUPLICATE,
        ):
            return None
        artifact = (
            await session.execute(
                select(ExternalArtifact).where(ExternalArtifact.action_log_id == existing.id)
            )
        ).scalar_one_or_none()
        if artifact is None:
            return None
        return artifact.external_id, artifact.external_url

    outcomes: list[tuple[Task, str, IssueOutcome]] = []
    for task in plan.tasks:
        for target_system in resolved_systems:
            adapter = _ADAPTERS[target_system]
            create_remote_fn, search_remote_fn = remotes[target_system]
            key = compute_idempotency_key(str(proposal.id), task, target_system)
            payload = adapter.build_payload(task)
            try:
                outcome = await adapter.create_idempotent(
                    idempotency_key=key,
                    payload=payload,
                    find_local=find_local,
                    search_remote=search_remote_fn,
                    create_remote=create_remote_fn,
                )
            except Exception as exc:  # one (task, system) failure must not abort the rest (FR-017)
                outcome = IssueOutcome(ActionLogStatus.FAILED, None, None, str(exc))
                log.warning(f"{target_system}_write_failed", idempotency_key=key, error=str(exc))

            response_json = {"external_id": outcome.external_id, "external_url": outcome.external_url}
            existing_log = await action_repo.get_by_idempotency_key(key)
            if existing_log is None:
                action_log = ActionLog(
                    proposal_id=proposal.id,
                    action_type=adapter.action_type,
                    target_system=target_system,
                    idempotency_key=key,
                    request_payload_json=payload,
                    response_payload_json=response_json,
                    status=outcome.status,
                    error_message=outcome.error,
                )
                await action_repo.add(action_log)
            else:  # retry / re-run: update the existing record, never insert a second row for this key
                existing_log.status = outcome.status
                existing_log.response_payload_json = response_json
                existing_log.error_message = outcome.error
                action_log = existing_log
                await session.flush()

            if outcome.external_id is not None:
                has_artifact = (
                    await session.execute(
                        select(ExternalArtifact).where(ExternalArtifact.action_log_id == action_log.id)
                    )
                ).scalar_one_or_none()
                if has_artifact is None:
                    await artifact_repo.add(
                        ExternalArtifact(
                            proposal_id=proposal.id,
                            action_log_id=action_log.id,
                            system=target_system,
                            artifact_type=adapter.artifact_type,
                            external_id=outcome.external_id,
                            external_url=outcome.external_url,
                            title=task.title,
                        )
                    )
            outcomes.append((task, target_system, outcome))

    all_failed = bool(outcomes) and all(o.status == ActionLogStatus.FAILED for _, _, o in outcomes)
    proposal.status = ProposalStatus.FAILED if all_failed else ProposalStatus.EXECUTED
    await session.commit()
    log.info(
        "execution_complete",
        proposal_id=str(proposal.id),
        status=proposal.status.value,
        succeeded=sum(o.status == ActionLogStatus.SUCCEEDED for _, _, o in outcomes),
        skipped=sum(o.status == ActionLogStatus.SKIPPED_DUPLICATE for _, _, o in outcomes),
        failed=sum(o.status == ActionLogStatus.FAILED for _, _, o in outcomes),
    )
    return outcomes
