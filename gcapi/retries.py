import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

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

    def __init__(self, backoff_factor: float, maximum_number_of_retries: int):
        self.backoff_factor = backoff_factor
        self.maximum_number_of_retries = maximum_number_of_retries
        self.earlier_number_of_retries: dict[int, int] = dict()

    def __call__(self) -> BaseRetryStrategy:
        return self.__class__(
            backoff_factor=self.backoff_factor,
            maximum_number_of_retries=self.maximum_number_of_retries,
        )

    def get_delay(self, latest_response: httpx.Response) -> Optional[Seconds]:
        if latest_response.status_code in (
            codes.BAD_GATEWAY,
            codes.SERVICE_UNAVAILABLE,
            codes.GATEWAY_TIMEOUT,
            codes.INSUFFICIENT_STORAGE,
            codes.TOO_MANY_REQUESTS,
        ):
            return self._backoff_retries(latest_response)
        else:
            return NO_RETRY

    def _backoff_retries(self, response):
        num_retries = self.earlier_number_of_retries.get(
            response.status_code, 0
        )
        if num_retries >= self.maximum_number_of_retries:
            return NO_RETRY
        else:
            self.earlier_number_of_retries[response.status_code] = (
                num_retries + 1
            )
            delay = self.backoff_factor * (2**num_retries)

            if "Retry-After" in response.headers:
                retry_after = response.headers["Retry-After"]
                # The HTTP header comes in two formats: integer seconds and HTTP-date
                try:
                    # Try to parse as integer seconds
                    delay = float(retry_after)
                except ValueError:
                    # Try to parse as HTTP-date
                    try:
                        retry_after_dt = parsedate_to_datetime(retry_after)
                    except (
                        ValueError,
                        # Python 3.9 throws a TypeError when it cannot parse the date
                        TypeError,
                    ):
                        pass
                    else:
                        now = datetime.datetime.now(
                            datetime.timezone.utc
                        ).replace(tzinfo=retry_after_dt.tzinfo)
                        delay = (retry_after_dt - now).total_seconds()
                        delay = max(0, delay)

            return delay
