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
            NO_RETRIES,
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
            [0.1, 0.2] * 3,
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
        # codes.TOO_MANY_REQUESTS with Retry-After header as HTTP-date
        (
            [
                Response(
                    codes.TOO_MANY_REQUESTS,
                    headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
                )
            ]
            * 2,
            [
                pytest.approx(0, abs=2),  # Will be mocked below
                pytest.approx(0, abs=2),
            ],
        ),
    ],
)
def test_selective_backoff_strategy(responses, delays):
    generator = SelectiveBackoffStrategy(
        backoff_factor=0.1, maximum_number_of_retries=8
    )
    strategy = generator()
    for response, expected_delay in zip(responses, delays):
        assert strategy.get_delay(response) == expected_delay
