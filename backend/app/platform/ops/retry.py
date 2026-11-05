"""Part 17.13: retry with backoff for calls that can fail for a moment (email, storage, AI).

    result = with_retry(lambda: adapter.send(msg), attempts=3, base_delay=0.5,
                        retry_if=lambda r: not r.success and is_transient(r.error))

Only transient problems are retried (timeouts, dropped connections, "try again", 429/5xx) --
a wrong password or a rejected address is returned straight away, never hammered.
"""

import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")
_TRANSIENT_WORDS = ("timed out", "timeout", "temporarily", "try again", "connection reset", "connection refused", "connection aborted",
                    "server disconnected", "unavailable", "too many requests", "rate limit", "429", "502", "503", "504", "eof occurred")


def is_transient(error: Optional[object]) -> bool:
    text = str(error or "").lower()
    return any(w in text for w in _TRANSIENT_WORDS)


def with_retry(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 0.5,
               retry_if: Optional[Callable[[T], bool]] = None, sleep: Callable[[float], None] = time.sleep) -> T:
    last_exc: Optional[BaseException] = None
    for i in range(attempts):
        try:
            result = fn()
        except (OSError, TimeoutError, ConnectionError) as exc:  # network trouble
            last_exc = exc
            if i + 1 >= attempts or not (is_transient(exc) or isinstance(exc, (TimeoutError, ConnectionError))):
                raise
        else:
            if retry_if is None or not retry_if(result) or i + 1 >= attempts:
                return result
        sleep(base_delay * (2 ** i))
    if last_exc is not None:
        raise last_exc
    return result  # pragma: no cover
