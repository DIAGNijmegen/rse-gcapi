from http import HTTPStatus

import pytest
import requests

from gcapi.adapters import RetryAdapter
from gcapi.retries import BaseRetryStrategy
from tests.utils import make_response, mock_adapter_responses

MOCK_REQUEST = requests.Request("GET", "https://example.test").prepare()
MOCK_RESPONSES = [
    make_response(status_code=HTTPStatus.NOT_FOUND),
    make_response(status_code=HTTPStatus.NOT_FOUND),
    make_response(status_code=HTTPStatus.OK),
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
        RetryAdapter(retry_strategy=object)  # type: ignore


def test_null_retries():
    adapter = RetryAdapter(retry_strategy=None)

    with mock_adapter_responses(adapter, MOCK_RESPONSES) as mock_info:
        response = adapter.send(MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_no_retry_strategy():
    adapter = RetryAdapter(retry_strategy=NoRetries)

    with mock_adapter_responses(adapter, MOCK_RESPONSES) as mock_info:
        response = adapter.send(MOCK_REQUEST)
        assert response is MOCK_RESPONSES[0]
        assert mock_info.num_requests == 1


def test_infinite_retry_strategy():
    adapter = RetryAdapter(retry_strategy=EndlessRetries)

    with mock_adapter_responses(adapter, MOCK_RESPONSES) as mock_info:
        response = adapter.send(MOCK_REQUEST)
        assert response is MOCK_RESPONSES[-1]
        assert mock_info.num_requests == len(MOCK_RESPONSES)
