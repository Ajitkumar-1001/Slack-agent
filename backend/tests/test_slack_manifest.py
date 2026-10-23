"""Static checks that docs/slack-app-manifest.yaml, docs/runbook.md and README.md stay in step with
the code: the manifest subscribes only to events slack/events.py handles and points at the routes
FastAPI actually serves, the runbook's demo prompt clears the FR-002 intent gate, and the README
documents every setting and links the public docs only."""

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.main import app
from slack.events import classify_message

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"


def _manifest() -> dict:
    return yaml.safe_load((DOCS / "slack-app-manifest.yaml").read_text())


def test_manifest_subscribes_only_to_handled_events():
    events = _manifest()["settings"]["event_subscriptions"]["bot_events"]
    # no assistant_thread_* — there is no handler for them in slack/events.py
    assert set(events) == {"app_mention", "message.im"}


def test_manifest_scopes_cover_events_and_replies():
    manifest = _manifest()
    scopes = set(manifest["oauth_config"]["scopes"]["bot"])
    assert {"app_mentions:read", "im:history", "chat:write"} <= scopes
    # users can't DM the bot (message.im) unless the App Home messages tab is on
    assert manifest["features"]["app_home"]["messages_tab_enabled"] is True


def test_manifest_urls_point_at_served_routes():
    settings = _manifest()["settings"]
    served = app.openapi()["paths"]
    urls = {
        "/slack/events": settings["event_subscriptions"]["request_url"],
        "/slack/actions": settings["interactivity"]["request_url"],
    }
    assert settings["interactivity"]["is_enabled"] is True
    for path, url in urls.items():
        assert path in served
        assert url == f"https://YOUR-HOST{path}"


def test_runbook_flags_t043_and_demo_prompt_passes_intent_gate():
    runbook = (DOCS / "runbook.md").read_text()
    assert "live demo (T043) has NOT been run" in runbook
    prompt = re.search(r"Post: `(@FlowPilot [^`]+)`", runbook)
    assert prompt
    assert classify_message(prompt.group(1))


def test_readme_documents_every_setting_and_flags_demo_not_run():
    readme = (REPO / "README.md").read_text()
    missing = [
        name.upper()
        for name in Settings.model_fields
        if f"`{name.upper()}`" not in readme
    ]
    assert not missing
    assert "has not been run yet" in readme


def test_readme_links_existing_docs():
    readme = (REPO / "README.md").read_text()
    for doc in (
        "docs/runbook.md",
        "docs/development.md",
        "docs/slack-app-manifest.yaml",
    ):
        assert f"]({doc})" in readme
        assert (REPO / doc).is_file()


@pytest.mark.parametrize("doc", ["README.md", "docs/development.md"])
def test_public_docs_do_not_reference_local_only_files(doc):
    # .specify/, Slack-agent/ and CLAUDE.md are gitignored, so links to them are dead for readers
    text = (REPO / doc).read_text()
    for local_only in (".specify", "Slack-agent", "CLAUDE.md"):
        assert local_only not in text
