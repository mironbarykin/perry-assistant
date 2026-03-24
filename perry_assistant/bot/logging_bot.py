from __future__ import annotations

"""PerryBot – a thin Bot subclass that logs every outgoing Telegram API call.

Overrides ``_do_post``, which is called by *every* Bot method (sendMessage,
editMessageText, answerCallbackQuery, etc.) and receives the fully-resolved
parameter dict.  The call-stack is inspected to find the immediate
perry_assistant function that triggered the outgoing call so that each log
entry records *which handler / service* sent the message.
"""

import sys
from typing import Any, List, Union

import telegram
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput

from perry_assistant.bot.handlers.stats import SKIP_ENDPOINTS, log_outgoing


class PerryBot(telegram.Bot):
    """telegram.Bot subclass with outgoing-message statistics logging."""

    async def _do_post(
        self,
        endpoint: str,
        data: JSONDict,
        *,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> Union[bool, JSONDict, List[JSONDict]]:
        if endpoint not in SKIP_ENDPOINTS:
            try:
                log_outgoing(endpoint, data, _caller_function())
            except Exception:  # pragma: no cover – logging must never crash the bot
                pass
        return await super()._do_post(
            endpoint,
            data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERRY_PREFIX = "perry_assistant."
_OWN_MODULE = __name__


def _caller_function() -> str:
    """Walk the synchronous call-stack and return the first perry_assistant
    frame that is *not* this module and not a telegram-library frame.

    Returns a string like ``"handlers.schedule.today"`` or ``"job"`` for
    background jobs.
    """
    frame = sys._getframe(1)  # start at _do_post itself
    try:
        while frame is not None:
            module: str = frame.f_globals.get("__name__", "")
            if module.startswith(_PERRY_PREFIX) and module != _OWN_MODULE:
                # Strip the package prefix for brevity
                short_module = module[len(_PERRY_PREFIX):]
                func = frame.f_code.co_name
                # Skip private helpers and the bot layer itself
                if not func.startswith("_") or func in (
                    "_send_markdown",
                    "_send_with_chunks",
                    "_reply_with_chunks",
                ):
                    return f"{short_module}.{func}"
            frame = frame.f_back
    finally:
        del frame
    return "unknown"
