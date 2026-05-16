from __future__ import annotations

import asyncio
import functools
import logging
import re
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[^\w\s]", "", text).lower().strip()


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 8.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
) -> Callable[[F], F]:
    """Decorator for exponential backoff retry logic on async functions.
    
    Args:
        max_retries: Maximum number of retries (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay between retries (default: 8.0)
        backoff_factor: Multiplier for delay each retry (default: 2.0)
        retryable_exceptions: Tuple of exception types to retry on.
            Defaults to: TimeoutError, ConnectionError, OSError, and
            exceptions with 'timeout' or 'connection' in their name.
    
    Returns:
        Decorated async function with retry logic.
        
    Example:
        @retry_with_backoff(max_retries=3)
        async def fetch_data():
            return await client.get(...)
    """
    if retryable_exceptions is None:
        retryable_exceptions = (TimeoutError, ConnectionError, OSError)

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    should_retry = _is_retryable(e, retryable_exceptions)
                    last_exception = e

                    if not should_retry or attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {attempt + 1} attempt(s): {type(e).__name__}: {e}"
                        )
                        raise

                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {type(e).__name__}: {e}"
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            if last_exception:
                raise last_exception

        return wrapper  # type: ignore[return-value]

    return decorator


def _is_retryable(exception: Exception, retryable_exceptions: tuple[type[Exception], ...]) -> bool:
    """Check if an exception should trigger a retry."""
    if isinstance(exception, retryable_exceptions):
        return True

    exception_name = type(exception).__name__.lower()
    if "timeout" in exception_name or "connection" in exception_name:
        return True

    if hasattr(exception, "status_code") and exception.status_code == 429:  # type: ignore[attr-defined]
        return True

    return False

