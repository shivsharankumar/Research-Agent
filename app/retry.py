import asyncio
import logging

logger = logging.getLogger(__name__)

"""exponential backoff is a common strategy for retrying operations that may fail due to transient issues, 
such as network errors or temporary unavailability of a service. The idea is to wait for progressively longer intervals between retries, 
which can help reduce the load on the system and increase the chances of success on subsequent attempts.

delay=delay*backoff is the formula for calculating the wait time before each retry.
"""

async def with_retry(coro_fn, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Call coro_fn() with exponential backoff. Raises the last exception if all retries fail."""
    last_exc = None
    wait = delay
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(f"Attempt {attempt}/{max_retries} failed: {exc}. Retrying in {wait:.1f}s")
                await asyncio.sleep(wait)
                wait *= backoff
    raise last_exc