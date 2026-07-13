"""T017 [US1] — request-classification test (FR-002, SC-005).

RED until T024 creates backend/slack/events.py.

Interface imposed on T024:
- ``classify_message(text: str) -> bool`` (True = a project-execution request).
  Must be deterministic / offline-testable for clear cases (a keyword/intent heuristic is
  fine for the MVP; if LLM-backed, expose a mockable seam). A False result is what gates
  the handler into the clarification reply and prevents any ProjectProposal from being created.
"""


def test_non_project_message_is_not_a_request():
    from slack.events import classify_message

    assert classify_message("hey, does anyone want to grab lunch?") is False


def test_project_execution_request_is_classified():
    from slack.events import classify_message

    assert (
        classify_message("create an execution plan for the onboarding launch in four weeks")
        is True
    )
