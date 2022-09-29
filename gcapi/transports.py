import asyncio
import logging
from functools import wraps
from time import sleep
from typing import Callable, Optional, Tuple

import httpx

from gcapi.retries import BaseRetryStrategy

logger = logging.getLogger(__name__)

Seconds = float


class BaseRetryTransport:
    def __init__(
        self,
        retry_strategy: Optional[Callable[..., BaseRetryStrategy]],
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

    def _handle_retry(
        self, retry_strategy, response
    ) -> Tuple[BaseRetryStrategy, Optional[Seconds]]:
        request: httpx.Request = response.request

        if retry_strategy is None:
            retry_strategy = self.retry_strategy()  # type: ignore

        retry_delay = retry_strategy.get_delay(response)
        if retry_delay is not None:
            error_phrase = httpx.codes.get_reason_phrase(response.status_code)
            logger.error(
                f"{request.method} request to {request.url} failed with "
                f"{response.status_code} status ('{error_phrase}'): "
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

    @wraps(httpx.HTTPTransport.handle_request)
    def handle_request(
        self, request: httpx.Request, *args, **kwargs
    ) -> httpx.Response:
        retry_strategy = None
        retry_delay: Optional[Seconds] = 0
        while True:
            if retry_delay:
                sleep(retry_delay)

            response = super().handle_request(request, *args, **kwargs)
            response.request = request

            if response.is_success or not self.retry_strategy:
                break

            retry_strategy, retry_delay = self._handle_retry(
                retry_strategy, response
            )

            if retry_delay is None:
                break
            else:
                # Close any connections kept open for this request
                response.close()
                continue

        return response


class AsyncRetryTransport(BaseRetryTransport, httpx.AsyncHTTPTransport):
    """Same as the RetryTransport but adapted for asynchronous clients"""

    @wraps(httpx.AsyncHTTPTransport.handle_async_request)
    async def handle_async_request(
        self, request: httpx.Request, *args, **kwargs
    ) -> httpx.Response:
        retry_strategy = None
        retry_delay: Optional[Seconds] = 0
        while True:
            if retry_delay:
                await asyncio.sleep(retry_delay)

            response = await super().handle_async_request(
                request, *args, **kwargs
            )
            response.request = request

            if response.is_success or not self.retry_strategy:
                break

            retry_strategy, retry_delay = self._handle_retry(
                retry_strategy, response
            )
            if retry_delay is None:
                break
            else:
                # Close any connections kept open for this request
                await response.aclose()
                continue

        return response
