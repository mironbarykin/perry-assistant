from __future__ import annotations

import json
import logging
from typing import Any

from telegram import Update
from telegram.ext import CallbackContext


logger = logging.getLogger("perry.stats")

# Sentinel returned when no content-type flag applies
_ABSENT = object()

# Endpoints that are pure infrastructure – polling, presence checks, webhook
# management. These are never logged by PerryBot as outgoing message events.
SKIP_ENDPOINTS: frozenset[str] = frozenset(
    {
        "getUpdates",
        "getMe",
        "getWebhookInfo",
        "setWebhook",
        "deleteWebhook",
        "close",
        "logOut",
    }
)


async def log_incoming_update(update: Update, context: CallbackContext) -> None:
    del context

    payload: dict[str, Any] = {
        "update_id": update.update_id,
        "update_type": _update_type(update),
        "user_id": update.effective_user.id if update.effective_user else None,
        "username": update.effective_user.username if update.effective_user else None,
        "full_name": update.effective_user.full_name if update.effective_user else None,
        "is_bot": update.effective_user.is_bot if update.effective_user else None,
        "chat_id": update.effective_chat.id if update.effective_chat else None,
        "chat_type": update.effective_chat.type if update.effective_chat else None,
    }

    # ── Regular / edited message ─────────────────────────────────────────
    msg = update.message or update.edited_message
    if msg:
        payload["message_id"] = msg.message_id
        payload["is_edited"] = update.edited_message is not None
        text = (msg.text or msg.caption or "").strip()
        if text:
            payload["text"] = text
            payload["command"] = text.split()[0] if text.startswith("/") else ""
        # Content-type flags
        content_type = _message_content_type(msg)
        if content_type:
            payload["content_type"] = content_type
        if msg.location:
            payload["location"] = {
                "lat": msg.location.latitude,
                "lon": msg.location.longitude,
            }
        if msg.contact:
            payload["contact_phone"] = msg.contact.phone_number
        if msg.poll:
            payload["poll_question"] = msg.poll.question
        if msg.dice:
            payload["dice_emoji"] = msg.dice.emoji
            payload["dice_value"] = msg.dice.value
        if msg.sticker:
            payload["sticker_emoji"] = msg.sticker.emoji
            payload["sticker_set"] = msg.sticker.set_name

    # ── Channel post ─────────────────────────────────────────────────────
    elif update.channel_post or update.edited_channel_post:
        post = update.channel_post or update.edited_channel_post
        payload["message_id"] = post.message_id
        payload["is_edited"] = update.edited_channel_post is not None
        text = (post.text or post.caption or "").strip()
        if text:
            payload["text"] = text

    # ── Callback query ────────────────────────────────────────────────────
    if update.callback_query:
        payload["callback_data"] = update.callback_query.data or ""
        if update.callback_query.message:
            payload["callback_message_id"] = update.callback_query.message.message_id

    # ── Inline query ──────────────────────────────────────────────────────
    if update.inline_query:
        payload["inline_query"] = update.inline_query.query

    # ── Poll / poll answer ────────────────────────────────────────────────
    if update.poll:
        payload["poll_id"] = update.poll.id
        payload["poll_question"] = update.poll.question
    if update.poll_answer:
        payload["poll_id"] = update.poll_answer.poll_id
        payload["poll_option_ids"] = list(update.poll_answer.option_ids)

    # ── Chat membership changes ───────────────────────────────────────────
    member_update = update.my_chat_member or update.chat_member
    if member_update:
        payload["member_chat_id"] = member_update.chat.id
        payload["member_old_status"] = member_update.old_chat_member.status
        payload["member_new_status"] = member_update.new_chat_member.status

    # ── Chat join request ─────────────────────────────────────────────────
    if update.chat_join_request:
        payload["join_request_chat_id"] = update.chat_join_request.chat.id

    stat_log = getattr(logger, "statistic", logger.info)
    stat_log("incoming=%s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _update_type(update: Update) -> str:
    if update.callback_query:
        return "callback_query"
    if update.inline_query:
        return "inline_query"
    if update.poll_answer:
        return "poll_answer"
    if update.poll:
        return "poll"
    if update.my_chat_member:
        return "my_chat_member"
    if update.chat_member:
        return "chat_member"
    if update.chat_join_request:
        return "chat_join_request"
    if update.edited_message:
        return "edited_message"
    if update.channel_post:
        return "channel_post"
    if update.edited_channel_post:
        return "edited_channel_post"
    if update.message:
        return _message_update_type(update.message)
    return "other"


def _message_update_type(msg: Any) -> str:
    """Return a fine-grained update type for regular messages."""
    if msg.location:
        return "location_message"
    if msg.text:
        return "text_message"
    if msg.photo:
        return "photo_message"
    if msg.voice:
        return "voice_message"
    if msg.video:
        return "video_message"
    if msg.audio:
        return "audio_message"
    if msg.document:
        return "document_message"
    if msg.sticker:
        return "sticker_message"
    if msg.animation:
        return "animation_message"
    if msg.video_note:
        return "video_note_message"
    if msg.contact:
        return "contact_message"
    if msg.poll:
        return "poll_message"
    if msg.dice:
        return "dice_message"
    if msg.venue:
        return "venue_message"
    return "message"


def _message_content_type(msg: Any) -> str | None:
    """Return a content_type label for non-text content, or None."""
    if msg.photo:
        return "photo"
    if msg.voice:
        return "voice"
    if msg.video:
        return "video"
    if msg.audio:
        return "audio"
    if msg.document:
        return "document"
    if msg.sticker:
        return "sticker"
    if msg.animation:
        return "animation"
    if msg.video_note:
        return "video_note"
    if msg.contact:
        return "contact"
    if msg.poll:
        return "poll"
    if msg.dice:
        return "dice"
    if msg.venue:
        return "venue"
    if msg.location:
        return "location"
    return None


def log_outgoing(
    endpoint: str,
    data: dict[str, Any],
    function: str,
) -> None:
    """Emit a STATS-level log line for every outgoing Telegram API call."""
    payload: dict[str, Any] = {
        "endpoint": endpoint,
        "function": function,
        "chat_id": data.get("chat_id"),
    }
    # Include text preview (first 300 chars) when present
    text = data.get("text") or data.get("caption")
    if text:
        payload["text_preview"] = str(text)[:300]
    if data.get("parse_mode"):
        payload["parse_mode"] = data["parse_mode"]
    if data.get("reply_to_message_id"):
        payload["reply_to_message_id"] = data["reply_to_message_id"]
    if data.get("reply_markup") is not None:
        payload["has_reply_markup"] = True
    # For answer_callback_query
    if data.get("callback_query_id"):
        payload["callback_query_id"] = data["callback_query_id"]
    # For edit operations
    if data.get("message_id"):
        payload["message_id"] = data["message_id"]
    # For other media types include a presence flag
    for media_key in ("photo", "voice", "video", "audio", "document", "sticker", "animation"):
        if data.get(media_key) is not None:
            payload["media_type"] = media_key
            break

    stat_log = getattr(logger, "statistic", logger.info)
    stat_log("outgoing=%s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

