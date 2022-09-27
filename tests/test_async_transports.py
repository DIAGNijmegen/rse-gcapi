import pytest
from httpx import Response, codes, Request

from gcapi.retries import RetryStrategy
from gcapi.transports import AsyncRetryTransport
from tests.utils import mock_base_transport_responses

MOCK_REQUEST = Request("GET", "https://example.com")
MOCK_RESPONSES = [
    Response(codes.NOT_FOUND),
    Response(codes.NOT_FOUND),
    Response(codes.OK),
]


@pytest.mark.anyio
async def test_invalid_retries():
    with pytest.raises(ValueError):
        AsyncRetryTransport(retries=object)


@pytest.mark.anyio
async def test_null_retries():
    transport = AsyncRetryTransport(retries=None)

    with mock_base_transport_responses(
        transport, MOCK_RESPONSES, asynchronous=True
    ) as mock_info:
        response = await transport.handle_async_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


@pytest.mark.anyio
async def test_no_retry_strategy():
    class NoRetries(RetryStrategy):
        def get_interval_ms(self, *_, **__):
            return None

    transport = AsyncRetryTransport(retries=NoRetries)

    with mock_base_transport_responses(
        transport, MOCK_RESPONSES, asynchronous=True
    ) as mock_info:
        response = await transport.handle_async_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


@pytest.mark.anyio
async def test_infinite_retry_strategy():
    class EndlessRetries(RetryStrategy):
        def get_interval_ms(self, *_, **__):
            return 0

    transport = AsyncRetryTransport(retries=EndlessRetries)

    with mock_base_transport_responses(
        transport, MOCK_RESPONSES, asynchronous=True
    ) as mock_info:
        response = await transport.handle_async_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[-1]
        assert mock_info.num_requests == 3
