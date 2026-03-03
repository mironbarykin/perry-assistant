from __future__ import annotations

import base64
import pickle
from typing import Any

from googleapiclient.discovery import build

from perry_assistant.config import AppConfig


class GmailClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._service_cache = None

    def _service(self):
        if self._service_cache is not None:
            return self._service_cache
        creds = None
        if self._config.token_pickle_file.exists():
            with self._config.token_pickle_file.open("rb") as token_file:
                creds = pickle.load(token_file)
        self._service_cache = build("gmail", "v1", credentials=creds)
        return self._service_cache

    def invalidate_service_cache(self) -> None:
        self._service_cache = None

    def get_basketball_email_ids(self, max_results: int = 10) -> list[dict[str, str]]:
        query = " OR ".join(f"from:{sender}" for sender in self._config.basketball_senders)
        response = self._service().users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()
        return response.get("messages", [])

    def get_message_content(self, message_id: str) -> dict[str, str]:
        message = self._service().users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()
        payload = message.get("payload", {})
        headers = {item["name"]: item["value"] for item in payload.get("headers", [])}
        text = _extract_payload_text(payload)

        return {
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "content": text,
        }


def _extract_payload_text(payload: dict[str, Any]) -> str:
    body_data = payload.get("body", {}).get("data")
    if body_data:
        return _decode(body_data)

    for part in payload.get("parts", []):
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain" and part.get("body", {}).get("data"):
            return _decode(part["body"]["data"])
        nested = _extract_payload_text(part)
        if nested:
            return nested
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode(errors="ignore")
