from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from perry_assistant.integrations.gmail_client import GmailClient


def _make_service(side_effects_list=None, return_value=None):
    """Build a mock service whose .users().messages().list(...).execute() or
    .get(...).execute() returns *return_value* or raises *side_effects_list*."""
    service = MagicMock()
    execute_mock = MagicMock()
    if side_effects_list is not None:
        execute_mock.side_effect = side_effects_list
    else:
        execute_mock.return_value = return_value
    service.users.return_value.messages.return_value.list.return_value.execute = execute_mock
    service.users.return_value.messages.return_value.get.return_value.execute = execute_mock
    return service, execute_mock


def test_get_basketball_email_ids_succeeds_normally(app_config):
    expected = [{"id": "abc"}]
    service, _ = _make_service(return_value={"messages": expected})
    client = GmailClient(app_config)

    with patch("perry_assistant.integrations.gmail_client.build", return_value=service):
        result = client.get_basketball_email_ids(max_results=5)

    assert result == expected


def test_get_basketball_email_ids_retries_on_broken_pipe(app_config):
    expected = [{"id": "xyz"}]
    service = MagicMock()
    execute_mock = MagicMock(side_effect=[BrokenPipeError, {"messages": expected}])
    service.users.return_value.messages.return_value.list.return_value.execute = execute_mock

    client = GmailClient(app_config)

    with patch("perry_assistant.integrations.gmail_client.build", return_value=service):
        result = client.get_basketball_email_ids(max_results=5)

    assert result == expected
    assert execute_mock.call_count == 2
    # Cache should have been invalidated and rebuilt (build called twice)


def test_get_basketball_email_ids_cache_invalidated_on_broken_pipe(app_config):
    """After a BrokenPipeError the service cache must be cleared so _service()
    rebuilds a fresh connection on retry."""
    service = MagicMock()
    execute_mock = MagicMock(side_effect=[BrokenPipeError, {"messages": []}])
    service.users.return_value.messages.return_value.list.return_value.execute = execute_mock

    client = GmailClient(app_config)

    with patch("perry_assistant.integrations.gmail_client.build", return_value=service) as mock_build:
        client.get_basketball_email_ids()

    # build() must have been called twice: once initially, once after cache invalidation
    assert mock_build.call_count == 2


def test_get_message_content_retries_on_broken_pipe(app_config):
    payload = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "From", "value": "a@b.com"},
                {"name": "Date", "value": "Mon, 1 Jan 2026"},
            ],
            "body": {},
            "parts": [],
        }
    }
    service = MagicMock()
    execute_mock = MagicMock(side_effect=[BrokenPipeError, payload])
    service.users.return_value.messages.return_value.get.return_value.execute = execute_mock

    client = GmailClient(app_config)

    with patch("perry_assistant.integrations.gmail_client.build", return_value=service):
        result = client.get_message_content("msg-id-1")

    assert result["subject"] == "Test"
    assert execute_mock.call_count == 2
