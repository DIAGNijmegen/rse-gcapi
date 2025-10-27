import logging
from collections.abc import Callable
from time import sleep

import httpx

from gcapi.retries import BaseRetryStrategy

logger = logging.getLogger(__name__)

Seconds = float


class BaseRetryTransport:
    def __init__(
        self,
        retry_strategy: Callable[..., BaseRetryStrategy] | None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.retry_strategy = retry_strategy
        if self.retry_strategy:
            obj = self.retry_strategy()
            if not isinstance(obj, BaseRetryStrategy):
                raise RuntimeError(
                    "Provided retries strategy should be None "
                    "or when called produce an instance of BaseRetry"
                )

    def _get_retry_delay(
        self,
        retry_strategy,
        response,
        request,
    ) -> tuple[BaseRetryStrategy | None, Seconds | None]:
        if self.retry_strategy is None:
            return None, None  # Noop
        elif retry_strategy is None:  # Initiate
            retry_strategy = self.retry_strategy()

        retry_delay = retry_strategy.get_delay(response)
        if retry_delay is not None:
            error_phrase = httpx.codes.get_reason_phrase(response.status_code)
            logger.error(
                f"{request.method} request to {request.url} failed with "
                f"{response.status_code} status ({error_phrase!r}): "
                f"retrying with {retry_delay}s delay"
            )

        return retry_strategy, retry_delay


class RetryTransport(BaseRetryTransport, httpx.HTTPTransport):
    """
    Transport that retries unsuccessful requests. Delays between retries are
    governed by a retry strategy.

    Once a request fails, a retries-strategy object is created from the provided
    retries class. This object is then queried to provide the delay in seconds
    via 'get_delay(response)'.

    The retry object should be an instance of BaseRetries.
    """

    def handle_request(
        self, request: httpx.Request, *args, **kwargs
    ) -> httpx.Response:
        retry_strategy = None
        while True:
            response = super().handle_request(request, *args, **kwargs)

            if response.is_success:
                break

            retry_strategy, retry_delay = self._get_retry_delay(
                retry_strategy,
                response,
                request,
            )

            if retry_delay is None:
                break
            else:
                # Close any connections kept open for this request
                response.close()
                sleep(retry_delay)

        return response
