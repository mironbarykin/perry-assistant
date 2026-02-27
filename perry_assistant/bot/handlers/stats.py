from __future__ import annotations

import json
import logging
from typing import Any

from telegram import Update
from telegram.ext import CallbackContext


logger = logging.getLogger("perry.stats")


async def log_incoming_update(update: Update, context: CallbackContext) -> None:
    del context

    payload: dict[str, Any] = {
        "update_id": update.update_id,
        "update_type": _update_type(update),
        "user_id": update.effective_user.id if update.effective_user else None,
        "username": update.effective_user.username if update.effective_user else None,
        "full_name": update.effective_user.full_name if update.effective_user else None,
        "chat_id": update.effective_chat.id if update.effective_chat else None,
    }

    if update.message:
        payload["message_id"] = update.message.message_id
        payload["text"] = (update.message.text or update.message.caption or "").strip()
        if payload["text"]:
            payload["command"] = payload["text"].split()[0] if str(payload["text"]).startswith("/") else ""
        if update.message.location:
            payload["location"] = {
                "lat": update.message.location.latitude,
                "lon": update.message.location.longitude,
            }

    if update.callback_query:
        payload["callback_data"] = update.callback_query.data or ""

    stat_log = getattr(logger, "statistic", logger.info)
    stat_log("incoming=%s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _update_type(update: Update) -> str:
    if update.callback_query:
        return "callback_query"
    if update.message and update.message.location:
        return "location_message"
    if update.message and update.message.text:
        return "text_message"
    if update.message:
        return "message"
    return "other"

