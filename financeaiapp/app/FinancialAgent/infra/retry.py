"""Retry decorator using tenacity for transient HTTP errors."""
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import httpx


def retry_api(max_attempts: int = 3):
    """Retry transient HTTP errors with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)
        ),
        reraise=True,
    )
