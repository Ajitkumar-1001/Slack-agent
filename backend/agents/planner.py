import structlog
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from agents.prompts import SYSTEM_PROMPT, build_user_message
from agents.schemas import ProjectPlan
from app.config import settings

log = structlog.get_logger()

_client = AsyncAnthropic(api_key=settings.anthropic_api_key)


class PlanGenerationError(Exception):
    """Raised when the model fails to produce a schema-valid ProjectPlan after one retry."""


async def _call_model(query: str, context: list[str]) -> dict:
    """The single LLM call. Returns the model's structured output as a raw dict so the
    caller validates it against ProjectPlan at the boundary (Constitution VII)."""
    response = await _client.messages.parse(
        model=settings.default_model_name,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(query, context)}],
        output_format=ProjectPlan,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise PlanGenerationError("model returned no parsed output")
    return parsed.model_dump()


async def generate_plan(*, query: str, context: list[str]) -> ProjectPlan:
    """Generate a validated ProjectPlan. On schema-validation failure: retry once, then
    safe-fail with PlanGenerationError — never surface an unvalidated plan (Constitution VII)."""
    last_error: ValidationError | None = None
    for attempt in range(2):
        raw = await _call_model(query, context)
        try:
            return ProjectPlan(**raw)
        except ValidationError as exc:
            last_error = exc
            log.warning("plan_validation_failed", attempt=attempt + 1)
    raise PlanGenerationError("ProjectPlan validation failed after retry") from last_error
