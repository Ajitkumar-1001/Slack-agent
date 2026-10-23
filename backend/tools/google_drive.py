"""Single Google Drive read-only retrieval interface (second Context Retrieval source; ADR-009).

Only this module calls the Drive API. Retrieved content is used for the active plan then
discarded — never persisted or indexed, by direct analogy to Constitution IX (ADR-009 Enforcement).
"""
import asyncio
import json
from typing import Any, Literal

import httpx
import structlog
from google.oauth2 import service_account
from pydantic import BaseModel

from app.config import settings
from tools.retry import send_with_retry

log = structlog.get_logger()

_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_MIME_TYPE_CLAUSE = (
    "(mimeType = 'application/vnd.google-apps.document'"
    " or mimeType = 'application/vnd.google-apps.spreadsheet'"
    " or mimeType = 'application/vnd.google-apps.presentation')"
)
# research.md Decision 8 — 10s (not the 30s write-adapter convention: this call sits on the
# approval-card critical path) and a 5-file cap (each match costs its own export round-trip).
_TIMEOUT = 10
_PAGE_SIZE = 5

RetrievalMode = Literal["drive", "unavailable"]


class DriveRetrievalResult(BaseModel):
    documents: list[str]
    retrieval_mode: RetrievalMode


class _HttpxAuthResponse:
    """Adapts an httpx.Response to google.auth.transport.Response's public interface."""

    def __init__(self, response: httpx.Response) -> None:
        self.status = response.status_code
        self.headers = response.headers
        self.data = response.content


class _HttpxAuthRequest:
    """Adapts httpx to google.auth.transport.Request's public interface — the sanctioned
    extension seam google-auth documents for transports it doesn't bundle (research.md
    Decision 1). Keeps httpx as the project's one HTTP client instead of pulling in `requests`
    via google.auth.transport.requests."""

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> _HttpxAuthResponse:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.request(method, url, content=body, headers=headers)
        return _HttpxAuthResponse(response)


async def _get_access_token() -> str:
    info = json.loads(settings.google_drive_credentials or "{}")
    credentials = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    # credentials.refresh() is synchronous (google-auth has no native async transport) — run it
    # off the event loop so a slow token exchange doesn't block concurrent request handling.
    await asyncio.to_thread(credentials.refresh, _HttpxAuthRequest())
    return credentials.token


async def _search_files(*, query: str, folder_scope: str | None, token: str) -> list[dict]:
    q = f"fullText contains '{query}' and {_MIME_TYPE_CLAUSE} and trashed = false"
    if folder_scope:
        q += f" and '{folder_scope}' in parents"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await send_with_retry(
            lambda: client.get(
                _DRIVE_FILES_URL,
                params={"q": q, "pageSize": _PAGE_SIZE},
                headers={"Authorization": f"Bearer {token}"},
            ),
            retry_5xx=True,
        )
        response.raise_for_status()
        files: list[dict] = response.json().get("files", [])
        return files


async def _export_file(*, file_id: str, mime_type: str, token: str) -> str:
    export_mime_type = _EXPORT_MIME_TYPES.get(mime_type, "text/plain")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await send_with_retry(
            lambda: client.get(
                f"{_DRIVE_FILES_URL}/{file_id}/export",
                params={"mimeType": export_mime_type},
                headers={"Authorization": f"Bearer {token}"},
            ),
            retry_5xx=True,
        )
        response.raise_for_status()
        return response.text


async def retrieve_context(*, query: str, folder_scope: str | None = None) -> DriveRetrievalResult:
    try:
        token = await _get_access_token()
        files = await _search_files(query=query, folder_scope=folder_scope, token=token)
        documents: list[str] = []
        for f in files:
            try:
                documents.append(
                    await _export_file(file_id=f["id"], mime_type=f["mimeType"], token=token)
                )
            except Exception as exc:  # one file's export failure must not abort the rest (FR-304)
                log.warning("google_drive_export_failed", file_id=f.get("id"), error=str(exc))
        result = DriveRetrievalResult(documents=documents, retrieval_mode="drive")
    except Exception as exc:
        log.warning("google_drive_retrieval_failed", error=str(exc))
        result = DriveRetrievalResult(documents=[], retrieval_mode="unavailable")

    log.info(
        "google_drive_retrieval",
        retrieval_mode=result.retrieval_mode,
        document_count=len(result.documents),
    )
    return result
