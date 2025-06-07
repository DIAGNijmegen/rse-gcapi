import httpx
import pytest

from gcapi.retries import BaseRetryStrategy
from gcapi.transports import RetryTransport
from tests.utils import mock_transport_responses

MOCK_REQUEST = httpx.Request("GET", "https://example.test")
MOCK_RESPONSES = [
    httpx.Response(httpx.codes.NOT_FOUND),
    httpx.Response(httpx.codes.NOT_FOUND),
    httpx.Response(httpx.codes.OK),
]


class NoRetries(BaseRetryStrategy):
    @staticmethod
    def get_delay(*_, **__):
        return None


class EndlessRetries(BaseRetryStrategy):
    @staticmethod
    def get_delay(*_, **__):
        return 0


def test_invalid_retries():
    with pytest.raises(RuntimeError):
        RetryTransport(retry_strategy=object)  # type: ignore


def test_null_retries():
    transport = RetryTransport(retry_strategy=None)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_no_retry_strategy():
    transport = RetryTransport(retry_strategy=NoRetries)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_infinite_retry_strategy():
    transport = RetryTransport(retry_strategy=EndlessRetries)

    with mock_transport_responses(transport, MOCK_RESPONSES) as mock_info:
        response = transport.handle_request(request=MOCK_REQUEST)
        assert response is MOCK_RESPONSES[-1]
        assert mock_info.num_requests == len(MOCK_RESPONSES)
