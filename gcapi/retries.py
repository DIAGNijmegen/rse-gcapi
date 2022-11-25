from typing import Dict, Optional

import httpx
from httpx import codes

Seconds = float


class BaseRetryStrategy:
    def get_delay(self, latest_response: httpx.Response) -> Optional[Seconds]:
        """
        Returns the number of seconds to pause before the next retry,
        based on the latest response.

        Optionally, if None is returned no retry is to be performed.
        """
        raise NotImplementedError(
            "The 'get_delay' method must be implemented."
        )  # pragma: no cover


NO_RETRY = None


class SelectiveBackoffStrategy(BaseRetryStrategy):
    """
    Retries responses with codes of transient server errors (i.e. 5xx)
    with an exponential backoff.

    Each response code has its own backoff counter.
    """

    def __init__(self, backoff_factor, maximum_number_of_retries):
        self.backoff_factor: float = backoff_factor
        self.maximum_number_of_retries: int = maximum_number_of_retries
        self.earlier_number_of_retries: Dict[int, int] = dict()

    def __call__(self) -> BaseRetryStrategy:
        return self.__class__(
            backoff_factor=self.backoff_factor,
            maximum_number_of_retries=self.maximum_number_of_retries,
        )

    def get_delay(self, latest_response: httpx.Response) -> Optional[Seconds]:
        if latest_response.status_code in (
            codes.INTERNAL_SERVER_ERROR,
            codes.BAD_GATEWAY,
            codes.SERVICE_UNAVAILABLE,
            codes.GATEWAY_TIMEOUT,
            codes.INSUFFICIENT_STORAGE,
        ):
            return self._backoff_retries(latest_response.status_code)
        else:
            return NO_RETRY

    def _backoff_retries(self, code):
        num_retries = self.earlier_number_of_retries.get(code, 0)
        if num_retries >= self.maximum_number_of_retries:
            return NO_RETRY
        else:
            self.earlier_number_of_retries[code] = num_retries + 1
            return self.backoff_factor * (2**num_retries)
