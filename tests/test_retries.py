import datetime
from http import HTTPStatus
from unittest import mock

import pytest

from gcapi.retries import SelectiveBackoffStrategy
from tests.utils import make_response

NO_RETRIES = [None]


@pytest.mark.parametrize(
    "responses,delays",
    [
        ([make_response(status_code=HTTPStatus.OK)], NO_RETRIES),
        ([make_response(status_code=HTTPStatus.UNAUTHORIZED)], NO_RETRIES),
        (  # No retry server errors
            [
                make_response(status_code=e)
                for e in (
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    HTTPStatus.NOT_IMPLEMENTED,
                    HTTPStatus.HTTP_VERSION_NOT_SUPPORTED,
                    HTTPStatus.VARIANT_ALSO_NEGOTIATES,
                    HTTPStatus.LOOP_DETECTED,
                    HTTPStatus.NOT_EXTENDED,
                    HTTPStatus.NETWORK_AUTHENTICATION_REQUIRED,
                )
            ],
            NO_RETRIES * 7,
        ),
        *(  # Backoff responses
            (
                [make_response(status_code=e)] * 10,
                [0.1, 0.2, 0.4, 0.8, 1.60, 3.20, 6.40, 12.8, None, None],
            )
            for e in (
                HTTPStatus.BAD_GATEWAY,
                HTTPStatus.SERVICE_UNAVAILABLE,
                HTTPStatus.GATEWAY_TIMEOUT,
                HTTPStatus.INSUFFICIENT_STORAGE,
            )
        ),
        (  # Mixed responses
            [
                make_response(status_code=HTTPStatus.BAD_GATEWAY),
                make_response(status_code=HTTPStatus.BAD_GATEWAY),
                make_response(status_code=HTTPStatus.GATEWAY_TIMEOUT),
                make_response(status_code=HTTPStatus.GATEWAY_TIMEOUT),
            ],
            [0.1, 0.2] * 2,
        ),
        # HTTPStatus.TOO_MANY_REQUESTS without Retry-After header
        (
            [make_response(status_code=HTTPStatus.TOO_MANY_REQUESTS)] * 10,
            [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, None, None],
        ),
        # HTTPStatus.TOO_MANY_REQUESTS with Retry-After header with garbage
        (
            [
                make_response(
                    status_code=HTTPStatus.TOO_MANY_REQUESTS,
                    headers={"Retry-After": "foo"},
                )
            ]
            * 10,
            [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, None, None],
        ),
        # HTTPStatus.TOO_MANY_REQUESTS with Retry-After header as integer seconds
        (
            [
                make_response(
                    status_code=HTTPStatus.TOO_MANY_REQUESTS,
                    headers={"Retry-After": "120"},
                )
            ]
            * 10,
            [120.0] * 8 + [None, None],
        ),
        # HTTPStatus.TOO_MANY_REQUESTS with Retry-After header as HTTP-date (in the past)
        (
            [
                make_response(
                    status_code=HTTPStatus.TOO_MANY_REQUESTS,
                    headers={"Retry-After": "Wed, 21 Oct 1990 07:28:00 GMT"},
                )
            ]
            * 2,
            [
                0,
                0,
            ],
        ),
        (
            # HTTPStatus.TOO_MANY_REQUESTS with Retry-After header as HTTP-date
            [
                make_response(
                    status_code=HTTPStatus.TOO_MANY_REQUESTS,
                    headers={"Retry-After": "Fri, 01 Jan 1999 12:00:10 GMT"},
                )
            ]
            * 2,
            [
                10,
                10,
            ],
        ),
    ],
)
def test_selective_backoff_strategy(responses, delays):
    fixed_date = datetime.datetime(
        1999, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
    )
    with mock.patch("gcapi.retries.datetime") as mock_datetime:
        mock_datetime.datetime.now.return_value = fixed_date
        mock_datetime.datetime.side_effect = (
            lambda *args, **kwargs: datetime.datetime(*args, **kwargs)
        )
        generator = SelectiveBackoffStrategy(
            backoff_factor=0.1, maximum_number_of_retries=8
        )
        strategy = generator()
        for response, expected_delay in zip(responses, delays, strict=True):
            assert strategy.get_delay(response) == expected_delay


def test_example_retry_strategy_usage(docs_path):
    from examples.upload_retry_strategy import UploadRetryStrategy

    strategy = UploadRetryStrategy()

    delay = strategy.get_delay(
        make_response(
            status_code=HTTPStatus.BAD_REQUEST,
            json={
                "non_field_errors": [
                    "You have created too many uploads. Please try again later."
                ]
            },
        )
    )

    assert delay == 300
