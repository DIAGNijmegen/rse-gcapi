import datetime
from unittest import mock

import pytest
from httpx import Response, codes

from gcapi.retries import SelectiveBackoffStrategy

NO_RETRIES = [None]


@pytest.mark.parametrize(
    "responses,delays",
    [
        ([Response(codes.OK)], NO_RETRIES),
        ([Response(codes.UNAUTHORIZED)], NO_RETRIES),
        (  # No retry server errors
            [
                Response(e)
                for e in (
                    codes.INTERNAL_SERVER_ERROR,
                    codes.NOT_IMPLEMENTED,
                    codes.HTTP_VERSION_NOT_SUPPORTED,
                    codes.VARIANT_ALSO_NEGOTIATES,
                    codes.LOOP_DETECTED,
                    codes.NOT_EXTENDED,
                    codes.NETWORK_AUTHENTICATION_REQUIRED,
                )
            ],
            NO_RETRIES * 7,
        ),
        *(  # Backoff responses
            (
                [Response(e)] * 10,
                [0.1, 0.2, 0.4, 0.8, 1.60, 3.20, 6.40, 12.8, None, None],
            )
            for e in (
                codes.BAD_GATEWAY,
                codes.SERVICE_UNAVAILABLE,
                codes.GATEWAY_TIMEOUT,
                codes.INSUFFICIENT_STORAGE,
            )
        ),
        (  # Mixed responses
            [
                Response(codes.BAD_GATEWAY),
                Response(codes.BAD_GATEWAY),
                Response(codes.GATEWAY_TIMEOUT),
                Response(codes.GATEWAY_TIMEOUT),
            ],
            [0.1, 0.2] * 2,
        ),
        # codes.TOO_MANY_REQUESTS without Retry-After header
        (
            [Response(codes.TOO_MANY_REQUESTS)] * 10,
            [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, None, None],
        ),
        # codes.TOO_MANY_REQUESTS with Retry-After header with garbage
        (
            [
                Response(
                    codes.TOO_MANY_REQUESTS,
                    headers={"Retry-After": "foo"},
                )
            ]
            * 10,
            [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, None, None],
        ),
        # codes.TOO_MANY_REQUESTS with Retry-After header as integer seconds
        (
            [
                Response(
                    codes.TOO_MANY_REQUESTS,
                    headers={"Retry-After": "120"},
                )
            ]
            * 10,
            [120.0] * 8 + [None, None],
        ),
        # codes.TOO_MANY_REQUESTS with Retry-After header as HTTP-date (in the past)
        (
            [
                Response(
                    codes.TOO_MANY_REQUESTS,
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
            # codes.TOO_MANY_REQUESTS with Retry-After header as HTTP-date
            [
                Response(
                    codes.TOO_MANY_REQUESTS,
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
        Response(
            codes.BAD_REQUEST,
            json={
                "non_field_errors": [
                    "You have created too many uploads. Please try again later."
                ]
            },
        )
    )

    assert delay == 300
