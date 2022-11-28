import pytest

from gcapi.transports import AsyncRetryTransport
from tests.test_transports import (
    MOCK_REQUEST,
    MOCK_RESPONSES,
    EndlessRetries,
    NoRetries,
)
from tests.utils import mock_transport_responses


@pytest.mark.anyio
async def test_invalid_retries():
    with pytest.raises(RuntimeError):
        AsyncRetryTransport(retry_strategy=object)


@pytest.mark.anyio
async def test_null_retries():
    transport = AsyncRetryTransport(retry_strategy=None)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = await transport.handle_async_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


@pytest.mark.anyio
async def test_no_retry_strategy():
    transport = AsyncRetryTransport(retry_strategy=NoRetries)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = await transport.handle_async_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


@pytest.mark.anyio
async def test_infinite_retry_strategy():
    transport = AsyncRetryTransport(retry_strategy=EndlessRetries)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = await transport.handle_async_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[-1]
        assert mock_info.num_requests == len(MOCK_RESPONSES)
