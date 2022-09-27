from time import sleep

import anyio
from httpx import HTTPTransport, AsyncHTTPTransport, HTTPStatusError

from gcapi.retries import RetryStrategy


def is_successful(response):
    try:
        response.raise_for_status()
    except HTTPStatusError:
        return False
    else:
        return True


class BaseRetryTransport:
    def __init__(self, retries, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if retries is not None and not issubclass(retries, RetryStrategy):
            raise ValueError(
                "Provided retries strategy should be None or an instance of RetryStrategy"
            )
        self.retry_strategy_cls = retries


class RetryTransport(BaseRetryTransport, HTTPTransport):
    def handle_request(self, *args, **kwargs):
        retry_strategy = None
        retry_interval = 0
        while retry_interval is not None:
            if retry_interval:
                sleep(retry_interval)

            response = super().handle_request(*args, **kwargs)

            if is_successful(response) or self.retry_strategy_cls is None:
                break
            if retry_strategy is None:
                retry_strategy = self.retry_strategy_cls()
            retry_interval = retry_strategy.get_interval(response)

        return response


class AsyncRetryTransport(BaseRetryTransport, AsyncHTTPTransport):
    async def handle_async_request(self, *args, **kwargs):
        retry_strategy = None
        retry_interval = 0
        while retry_interval is not None:
            if retry_interval:
                await anyio.sleep(retry_interval)

            response = await super().handle_async_request(*args, **kwargs)

            if is_successful(response) or self.retry_strategy_cls is None:
                break
            if retry_strategy is None:
                retry_strategy = self.retry_strategy_cls()
            retry_interval = retry_strategy.get_interval(response)

        return response
