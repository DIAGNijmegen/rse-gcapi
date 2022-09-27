import httpx
import pytest

from gcapi.retries import RetryStrategy
from gcapi.transports import RetryTransport
from tests.utils import mock_transport_responses

MOCK_REQUEST = httpx.Request("GET", "https://example.com")
MOCK_RESPONSES = [
    httpx.Response(httpx.codes.NOT_FOUND),
    httpx.Response(httpx.codes.NOT_FOUND),
    httpx.Response(httpx.codes.OK),
]


class NoRetries(RetryStrategy):
    @staticmethod
    def get_interval(*_, **__):
        return None


class EndlessRetries(RetryStrategy):
    @staticmethod
    def get_interval(*_, **__):
        return 0


def test_invalid_retries():
    with pytest.raises(ValueError):
        RetryTransport(retries=object)


def test_null_retries():
    transport = RetryTransport(retries=None)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_no_retry_strategy():
    transport = RetryTransport(retries=NoRetries)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_infinite_retry_strategy():
    transport = RetryTransport(retries=EndlessRetries)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[-1]
        assert mock_info.num_requests == len(MOCK_RESPONSES)
