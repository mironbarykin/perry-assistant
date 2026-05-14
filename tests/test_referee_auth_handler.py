from __future__ import annotations

import asyncio
import pickle
from types import SimpleNamespace

from perry_assistant.bot.handlers.auth import handle_auth_code


class _FakeFlow:
    def __init__(self) -> None:
        self.credentials = {"token": "new-token"}
        self.received_code: str | None = None

    def fetch_token(self, code: str) -> None:
        self.received_code = code


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class _FakeRefereeService:
    def __init__(self) -> None:
        self.refresh_called = False

    def refresh_google_clients(self) -> None:
        self.refresh_called = True


def test_handle_auth_code_refreshes_cached_google_clients(app_config):
    app_config.data_dir.mkdir(parents=True, exist_ok=True)
    flow = _FakeFlow()
    message = _FakeMessage("4/abc123")
    referee_service = _FakeRefereeService()
    services = SimpleNamespace(config=app_config, referee_service=referee_service)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"services": services, "pending_auth": {"flow": flow, "awaiting_code": True}}))
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=app_config.miron_id))

    asyncio.run(handle_auth_code(update, context))

    assert flow.received_code == "4/abc123"
    assert referee_service.refresh_called is True
    assert message.replies == ["Google authentication updated."]
    assert context.application.bot_data["pending_auth"] is None
    with app_config.token_pickle_file.open("rb") as token_file:
        assert pickle.load(token_file) == {"token": "new-token"}
