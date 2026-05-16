from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging
import socket
import sys
import traceback
from pathlib import Path

import telegram
from google.auth.exceptions import RefreshError
from telegram import Update
from telegram.ext import ContextTypes

from perry_assistant.bot.handlers.auth import send_auth_link_to_admin
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.utils import retry_with_backoff


logger = logging.getLogger(__name__)

# Telegram's hard limit is 4096, but we account for HTML escaping
# and add buffer for other formatting
MAX_MESSAGE_LENGTH = 4000


def _check_network_health() -> str:
    """Perform basic network diagnostics and return a formatted status string."""
    diagnostics = []
    
    try:
        socket.gethostbyname("api.telegram.org")
        diagnostics.append("✓ DNS resolution working")
    except (socket.gaierror, socket.error) as e:
        diagnostics.append(f"✗ DNS resolution failed: {e}")
    
    try:
        sock = socket.create_connection(("api.telegram.org", 443), timeout=5)
        sock.close()
        diagnostics.append("✓ Telegram API connectivity OK")
    except (socket.timeout, socket.error, OSError) as e:
        diagnostics.append(f"✗ Telegram API unreachable: {e}")
    
    return "\n".join(diagnostics) if diagnostics else "Network check inconclusive"


def _is_network_error(error: Exception) -> bool:
    """Check if an error is likely network-related."""
    network_indicators = {
        "timeout",
        "connection",
        "reset",
        "closed",
        "refused",
        "unreachable",
        "dns",
        "host",
        "pool",
        "socket",
    }
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    return any(
        indicator in error_str or indicator in error_type
        for indicator in network_indicators
    ) or isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            ConnectionRefusedError,
            ConnectionResetError,
            socket.error,
            OSError,
        ),
    )


async def global_error_notify(
    update: object | Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    error: Exception,
) -> None:
    """Notify admin of errors via Telegram with fallback to file logging."""
    try:
        services = context.application.bot_data["services"]
    except (KeyError, AttributeError, TypeError):
        logger.exception("Failed to access services from context, falling back to file logging")
        _log_error_to_file(update, error)
        return

    if isinstance(error, RefreshError):
        await _handle_refresh_error(update, context, error)
        return

    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    logger.error(tb)

    timestamp = dt.datetime.now(BERLIN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    user_name = "JobQueue"
    chat_id = None
    if isinstance(update, Update):
        user_name = getattr(update.effective_user, "username", "Unknown")
        chat_id = getattr(update.effective_chat, "id", None)

    safe_tb = html.escape(tb)
    admin_message = (
        f"Error during {user_name}\n"
        f"Timestamp: {timestamp}\n"
        f"<pre>{safe_tb}</pre>"
    )
    
    # Include network diagnostics if error might be network-related
    if _is_network_error(error):
        diag = _check_network_health()
        admin_message += f"\n\nNetwork Status:\n<pre>{html.escape(diag)}</pre>"

    try:
        await _send_error_notification(
            context, services.config.miron_id, admin_message
        )
    except Exception as notify_error:
        logger.exception("Failed to send error notification to admin, falling back to file logging")
        _log_error_to_file(update, error, extra_context=f"Failed to notify admin: {notify_error}")

    if chat_id and chat_id != services.config.miron_id:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Your request failed and the admin was notified.",
            )
        except Exception as user_notify_error:
            logger.warning(f"Failed to notify user {chat_id} of error: {user_notify_error}")


async def _handle_refresh_error(
    update: object | Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    error: RefreshError,
) -> None:
    """Handle Google authentication refresh errors gracefully."""
    try:
        if isinstance(update, Update) and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Google authentication expired. Admin has been notified.",
                )
            except Exception as e:
                logger.warning(f"Failed to send auth error message to user: {e}")
        
        try:
            await send_auth_link_to_admin(context, "Google token expired.")
        except Exception as e:
            logger.exception("Failed to send auth link to admin")
            _log_error_to_file(update, error, extra_context=f"Auth error notification failed: {e}")
    except Exception as e:
        logger.exception("Unexpected error in refresh error handler")
        _log_error_to_file(update, error, extra_context=f"RefreshError handler failed: {e}")


@retry_with_backoff(
    max_retries=3,
    initial_delay=1.0,
    max_delay=8.0,
    retryable_exceptions=(TimeoutError, ConnectionError, OSError),
)
async def _send_error_notification(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: str,
) -> None:
    """Send error notification with message chunking for Telegram's 4096 char limit."""
    chunks = _chunk_message(message, MAX_MESSAGE_LENGTH)
    
    for i, chunk in enumerate(chunks):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=telegram.constants.ParseMode.HTML,
            )
        except telegram.error.TelegramError as e:
            if i == 0:
                raise
            logger.warning(f"Failed to send error notification chunk {i + 1}/{len(chunks)}: {e}")


def _chunk_message(message: str, max_length: int) -> list[str]:
    """Split a message into chunks respecting max_length."""
    if len(message) <= max_length:
        return [message]

    chunks = []
    current_chunk = ""

    for line in message.split("\n"):
        if len(current_chunk) + len(line) + 1 <= max_length:
            current_chunk += line + "\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.rstrip())
            current_chunk = line + "\n"

    if current_chunk:
        chunks.append(current_chunk.rstrip())

    return chunks if chunks else [""] * ((len(message) // max_length) + 1)


def _log_error_to_file(
    update: object | Update | None,
    error: Exception,
    extra_context: str = "",
) -> None:
    """Fallback: log error to stderr and file when Telegram notification fails."""
    try:
        timestamp = dt.datetime.now(BERLIN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        user_name = "JobQueue"
        chat_id = None

        if isinstance(update, Update):
            user_name = getattr(update.effective_user, "username", "Unknown")
            chat_id = getattr(update.effective_chat, "id", None)

        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        
        fallback_msg = (
            f"[{timestamp}] UNHANDLED ERROR\n"
            f"User: {user_name}\n"
            f"Chat ID: {chat_id}\n"
        )
        if extra_context:
            fallback_msg += f"Context: {extra_context}\n"
        fallback_msg += f"Traceback:\n{tb}"

        sys.stderr.write(fallback_msg + "\n")
        sys.stderr.flush()
        logger.critical(f"Error notification failed, logged to stderr: {fallback_msg}")
    except Exception as e:
        sys.stderr.write(f"CRITICAL: Error handler failed completely: {e}\n")
        sys.stderr.flush()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler that prevents uncaught exceptions from crashing the bot."""
    try:
        error = getattr(context, "error", None) or Exception("Unknown error")
        await global_error_notify(update, context, error)
    except Exception as e:
        logger.exception("Error handler itself failed")
        _log_error_to_file(update, e)

