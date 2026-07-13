"""T004-T005 [US1] — Google Drive retrieval adapter tests (FR-302; ADR-009; contracts/tool-adapters.md).

RED until T009 creates backend/tools/google_drive.py.

Interface imposed on T009:
- ``class DriveRetrievalResult(BaseModel): documents: list[str]; retrieval_mode: Literal["drive", "unavailable"]``
- ``async retrieve_context(*, query: str, folder_scope: str | None = None) -> DriveRetrievalResult``
  orchestrates ``_get_access_token()``, ``_search_files(*, query, folder_scope, token) -> list[dict]``,
  ``_export_file(*, file_id, mime_type, token) -> str`` (module-level, patchable) — any exception from
  any of the three is caught and degrades to ``DriveRetrievalResult(documents=[], retrieval_mode="unavailable")``,
  never raised (research.md Decision 5; FR-304).
- A per-file ``_export_file`` failure is skipped, not fatal to the whole call (research.md Decision 7).
- ``_search_files`` itself builds the Drive ``q`` filter (``fullText contains``, the three Docs/Sheets/
  Slides ``mimeType`` clauses, ``trashed = false``, optionally ``'{folder_scope}' in parents``) and
  calls ``GET https://www.googleapis.com/drive/v3/files`` via ``httpx.AsyncClient(timeout=10)`` with
  ``params={"q": ..., "pageSize": 5}`` (research.md Decision 8; FR-302, FR-304a).
"""
import pytest


# ---- T004: retrieve_context orchestration (success path + per-file export failure) ----


@pytest.mark.asyncio
async def test_returns_drive_mode_with_documents_when_search_and_export_succeed(monkeypatch):
    import tools.google_drive as gd

    async def fake_token():
        return "tok"

    async def fake_search(*, query, folder_scope, token):
        assert token == "tok"
        return [
            {"id": "doc1", "mimeType": "application/vnd.google-apps.document", "name": "Spec"},
            {"id": "sheet1", "mimeType": "application/vnd.google-apps.spreadsheet", "name": "Plan"},
        ]

    async def fake_export(*, file_id, mime_type, token):
        return f"content of {file_id}"

    monkeypatch.setattr(gd, "_get_access_token", fake_token)
    monkeypatch.setattr(gd, "_search_files", fake_search)
    monkeypatch.setattr(gd, "_export_file", fake_export)

    result = await gd.retrieve_context(query="onboarding plan")

    assert result.retrieval_mode == "drive"
    assert result.documents == ["content of doc1", "content of sheet1"]


@pytest.mark.asyncio
async def test_single_file_export_failure_is_skipped_others_still_returned(monkeypatch):
    import tools.google_drive as gd

    async def fake_token():
        return "tok"

    async def fake_search(*, query, folder_scope, token):
        return [
            {"id": "bad", "mimeType": "application/vnd.google-apps.document", "name": "TooBig"},
            {"id": "good", "mimeType": "application/vnd.google-apps.document", "name": "Fine"},
        ]

    async def fake_export(*, file_id, mime_type, token):
        if file_id == "bad":
            raise RuntimeError("simulated 403 exportSizeLimitExceeded")
        return "content of good"

    monkeypatch.setattr(gd, "_get_access_token", fake_token)
    monkeypatch.setattr(gd, "_search_files", fake_search)
    monkeypatch.setattr(gd, "_export_file", fake_export)

    result = await gd.retrieve_context(query="x")

    assert result.retrieval_mode == "drive"
    assert result.documents == ["content of good"]


@pytest.mark.asyncio
async def test_returns_unavailable_and_never_raises_when_search_fails(monkeypatch):
    import tools.google_drive as gd

    async def fake_token():
        return "tok"

    async def fake_search(*, query, folder_scope, token):
        raise RuntimeError("simulated Drive API error")

    monkeypatch.setattr(gd, "_get_access_token", fake_token)
    monkeypatch.setattr(gd, "_search_files", fake_search)

    result = await gd.retrieve_context(query="x")

    assert result.retrieval_mode == "unavailable"
    assert result.documents == []


@pytest.mark.asyncio
async def test_returns_unavailable_and_never_raises_when_token_exchange_fails(monkeypatch):
    import tools.google_drive as gd

    async def fake_token():
        raise RuntimeError("simulated token-exchange failure")

    monkeypatch.setattr(gd, "_get_access_token", fake_token)

    result = await gd.retrieve_context(query="x")

    assert result.retrieval_mode == "unavailable"
    assert result.documents == []


@pytest.mark.asyncio
async def test_returns_unavailable_when_credentials_json_is_malformed(monkeypatch):
    """T013 [US2] — malformed-credentials failure containment (research.md Decision 5; FR-304).
    Failed token exchange and failed files.list/files.export are already covered above; this
    adds the two T013-specific cases those don't: malformed credential JSON, and a timeout."""
    import tools.google_drive as gd
    from app.config import settings

    monkeypatch.setattr(settings, "google_drive_credentials", "{not valid json")

    result = await gd.retrieve_context(query="x")

    assert result.retrieval_mode == "unavailable"
    assert result.documents == []


@pytest.mark.asyncio
async def test_returns_unavailable_when_a_call_exceeds_the_timeout(monkeypatch):
    """T013 [US2] — a simulated httpx.TimeoutException (any leg exceeding the 10s timeout —
    research.md Decision 8; FR-304a) degrades to unavailable, never propagates."""
    import httpx

    import tools.google_drive as gd

    async def timing_out_token():
        raise httpx.TimeoutException("simulated timeout exceeding 10s")

    monkeypatch.setattr(gd, "_get_access_token", timing_out_token)

    result = await gd.retrieve_context(query="x")

    assert result.retrieval_mode == "unavailable"
    assert result.documents == []


# ---- T005: _search_files query/request construction ----


class _FakeResponse:
    def __init__(self, json_body):
        self._json = json_body

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Captures the constructor timeout and the .get() call's params — mirrors slack_rts.py's
    own _FakeClient/_FakeBoltApp pattern for inspecting a constructed outbound request."""

    last_timeout = None
    last_url = None
    last_params = None
    last_headers = None

    def __init__(self, timeout=None):
        _FakeAsyncClient.last_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeAsyncClient.last_url = url
        _FakeAsyncClient.last_params = params
        _FakeAsyncClient.last_headers = headers
        return _FakeResponse({"files": []})


@pytest.mark.asyncio
async def test_search_query_includes_fulltext_and_mimetype_clauses(monkeypatch):
    import tools.google_drive as gd

    monkeypatch.setattr(gd.httpx, "AsyncClient", _FakeAsyncClient)
    await gd._search_files(query="onboarding", folder_scope=None, token="tok")

    q = _FakeAsyncClient.last_params["q"]
    assert "fullText contains 'onboarding'" in q
    assert "application/vnd.google-apps.document" in q
    assert "application/vnd.google-apps.spreadsheet" in q
    assert "application/vnd.google-apps.presentation" in q
    assert "trashed = false" in q
    assert "in parents" not in q


@pytest.mark.asyncio
async def test_folder_scope_appended_to_query_when_provided(monkeypatch):
    import tools.google_drive as gd

    monkeypatch.setattr(gd.httpx, "AsyncClient", _FakeAsyncClient)
    await gd._search_files(query="onboarding", folder_scope="FOLDER123", token="tok")

    q = _FakeAsyncClient.last_params["q"]
    assert "'FOLDER123' in parents" in q


@pytest.mark.asyncio
async def test_search_request_includes_pagesize_5(monkeypatch):
    import tools.google_drive as gd

    monkeypatch.setattr(gd.httpx, "AsyncClient", _FakeAsyncClient)
    await gd._search_files(query="x", folder_scope=None, token="tok")

    assert _FakeAsyncClient.last_params["pageSize"] == 5


@pytest.mark.asyncio
async def test_search_call_constructed_with_timeout_10(monkeypatch):
    import tools.google_drive as gd

    monkeypatch.setattr(gd.httpx, "AsyncClient", _FakeAsyncClient)
    await gd._search_files(query="x", folder_scope=None, token="tok")

    assert _FakeAsyncClient.last_timeout == 10
