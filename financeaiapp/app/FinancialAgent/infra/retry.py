"""Retry decorator using tenacity for transient HTTP errors."""
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
import httpx


def _is_transient(exc: BaseException) -> bool:
    """True for network-level transient errors and 5xx/429 responses.

    4xx other than 429 are treated as permanent (bad request / auth) and
    are NOT retried.
    """
    if isinstance(
        exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status >= 500 or status == 429
    return False


def retry_api(max_attempts: int = 3):
    """Retry transient HTTP errors with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient),
        reraise=True,
    )
