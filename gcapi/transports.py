from time import sleep

import anyio
from httpx import HTTPTransport, AsyncHTTPTransport

from gcapi.retries import BaseRetries


class BaseRetryTransport:
    def __init__(self, retries, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_strategy_cls = retries

        if self.retry_strategy_cls:
            obj = self.retry_strategy_cls()
            if not isinstance(obj, BaseRetries):
                raise ValueError(
                    "Provided retries strategy should be None or when called produce an instance of BaseRetry"
                )


class RetryTransport(BaseRetryTransport, HTTPTransport):
    """
    Transport that retries unsuccessful requests. Delays between retries are governed by a retry strategy.
    Once a request fails, a retries-strategy object is created from the provided retries class.
    This object is then queried to provide the delay in seconds (via 'get_delay(response)').

    The retry object should be an instance of BaseRetries.
    """

    def handle_request(self, *args, **kwargs):
        retry_strategy = None
        retry_delay = 0
        while retry_delay is not None:
            if retry_delay:
                sleep(retry_delay)

            response = super().handle_request(*args, **kwargs)

            if response.is_success or not self.retry_strategy_cls:
                break

            if retry_strategy is None:
                retry_strategy = self.retry_strategy_cls()
            retry_delay = retry_strategy.get_delay(response)

        return response


class AsyncRetryTransport(BaseRetryTransport, AsyncHTTPTransport):
    """Same as the RetryTransport but adapted for asynchronous clients"""

    async def handle_async_request(self, *args, **kwargs):
        retry_strategy = None
        retry_delay = 0
        while retry_delay is not None:
            if retry_delay:
                await anyio.sleep(retry_delay)

            response = await super().handle_async_request(*args, **kwargs)

            if response.is_success or not self.retry_strategy_cls:
                break

            if retry_strategy is None:
                retry_strategy = self.retry_strategy_cls()
            retry_delay = retry_strategy.get_delay(response)

        return response
