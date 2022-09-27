from time import sleep

import anyio
import httpx

from gcapi.retries import RetryStrategy


def is_successful(response):
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        return False
    else:
        return True


class RetryTransport(httpx.BaseTransport):
    def __init__(self, retries, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if retries is not None and not issubclass(retries, RetryStrategy):
            raise ValueError(
                "Provided retries strategy should be None or an instance of RetryStrategy"
            )
        self.retries_cls = retries

    def handle_request(self, *args, **kwargs):
        if self.retries_cls is None:
            return super().handle_request(*args, **kwargs)

        retries = self.retries_cls()
        interval_ms = 0
        while interval_ms is not None:
            sleep(interval_ms / 1000)
            response = super().handle_request(*args, **kwargs)
            if is_successful(response):
                break
            interval_ms = retries.get_interval_ms(response)

        return response


class AsyncRetryTransport(httpx.AsyncBaseTransport):
    def __init__(self, retries, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if retries is not None and not issubclass(retries, RetryStrategy):
            raise ValueError(
                "Provided retries strategy should be None or an instance of RetryStrategy"
            )
        self.retries_cls = retries

    async def handle_async_request(self, *args, **kwargs):
        if self.retries_cls is None:
            return await super().handle_async_request(*args, **kwargs)

        retries = self.retries_cls()
        interval_ms = 0
        while interval_ms is not None:
            await anyio.sleep(interval_ms / 1000)
            response = await super().handle_async_request(*args, **kwargs)
            if is_successful(response):
                break
            interval_ms = retries.get_interval_ms(response)

        return response
