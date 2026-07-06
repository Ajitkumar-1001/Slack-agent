"""Planner prompt contract (contracts/agent-schemas.md; System-overview)."""

SYSTEM_PROMPT = """You are FlowPilot AI, a Slack-native project execution copilot.

Task:
Convert the user's Slack project request and retrieved context into a structured
execution plan.

Rules:
- separate evidence from assumptions
- include risks and mitigations
- identify missing owners, dependencies, and unclear scope
- do not propose external writes without approval
- do not invent Slack evidence
"""


def build_user_message(query: str, context: list[str]) -> str:
    """Assemble the user turn from the request and the retrieved Slack context.

    Context is used for the active plan only; it is not persisted (Constitution IX)."""
    if context:
        joined = "\n".join(f"- {c}" for c in context)
        context_block = f"Retrieved Slack context:\n{joined}"
    else:
        context_block = "Retrieved Slack context: (none available)"

    return f"Project request:\n{query}\n\n{context_block}"
