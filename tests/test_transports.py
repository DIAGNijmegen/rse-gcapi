import httpx
import pytest

from gcapi.retries import RetryStrategy
from gcapi.transports import RetryTransport
from tests.utils import mock_base_transport_responses

MOCK_REQUEST = httpx.Request("GET", "https://example.com")
MOCK_RESPONSES = [
    httpx.Response(httpx.codes.NOT_FOUND),
    httpx.Response(httpx.codes.NOT_FOUND),
    httpx.Response(httpx.codes.OK),
]


def test_invalid_retries():
    with pytest.raises(ValueError):
        RetryTransport(retries=object)


def test_null_retries():
    transport = RetryTransport(retries=None)

    with mock_base_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_no_retry_strategy():
    class NoRetries(RetryStrategy):
        def get_interval_ms(self, *_, **__):
            return None

    transport = RetryTransport(retries=NoRetries)

    with mock_base_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_infinite_retry_strategy():
    class EndlessRetries(RetryStrategy):
        def get_interval_ms(self, *_, **__):
            return 0

    transport = RetryTransport(retries=EndlessRetries)

    with mock_base_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[-1]
        assert mock_info.num_requests == 3
