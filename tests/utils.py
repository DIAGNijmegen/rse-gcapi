import contextlib
from functools import wraps
from time import sleep

from httpx import AsyncHTTPTransport, HTTPStatusError, HTTPTransport

import gcapi
from gcapi.exceptions import ObjectNotFound
from tests.scripts.constants import USER_TOKENS

ADMIN_TOKEN = USER_TOKENS["admin"]
READERSTUDY_TOKEN = USER_TOKENS["readerstudy"]
DEMO_PARTICIPANT_TOKEN = USER_TOKENS["demop"]
ARCHIVE_TOKEN = USER_TOKENS["archive"]


def recurse_call(func):
    def wrapper(*args, **kwargs):
        last_error = None
        for _ in range(60):
            try:
                result = func(*args, **kwargs)
                break
            except (
                HTTPStatusError,
                ValueError,
                # Permissions are sometimes delayed, shows as ObjectNotFound
                ObjectNotFound,
            ) as e:
                last_error = e
                sleep(0.5)
        else:
            raise TimeoutError from last_error
        return result

    return wrapper


def async_recurse_call(func):
    async def wrapper(*args, **kwargs):
        last_error = None
        for _ in range(60):
            try:
                result = await func(*args, **kwargs)
                break
            except (
                HTTPStatusError,
                ValueError,
                # Permissions are sometimes delayed, shows as ObjectNotFound
                ObjectNotFound,
            ) as e:
                last_error = e
                sleep(0.5)
        else:
            raise TimeoutError from last_error
        return result

    return wrapper


@contextlib.contextmanager
def mock_transport_responses(transport, responses):
    """
    Mocks the responses in the provided HTTPX transport by
    shadowing the request handlers just before the HTTPTransport
    or AsyncHTTPTransport in the transport's MRO.

    Returns a class from which some metadata about the mocking can
    be read (such as number of requests).
    """
    responses = iter(responses)

    class ResponseMetaData:
        num_requests = 0

    class MockTransport:
        @staticmethod
        def handle_request(request, *_, **__):
            try:
                ResponseMetaData.num_requests += 1
                response = responses.__next__()
                response.request = request
                return response
            except StopIteration as e:
                raise RuntimeError("Ran out of mock responses") from e

        async def handle_async_request(self, *args, **kwargs):
            return self.handle_request(*args, **kwargs)

    bases = []
    for cls in transport.__class__.mro():
        if cls in [HTTPTransport, AsyncHTTPTransport]:
            bases.append(MockTransport)
        bases.append(cls)
    old_class = transport.__class__
    new_class = type(
        old_class.__name__,
        tuple(bases),
        dict(old_class.__dict__),
    )
    try:
        transport.__class__ = new_class
        yield ResponseMetaData
    finally:
        transport.__class__ = old_class


def sync_generator_test(test):
    """
    Decorator allowing for unit testing the synchronous generators that
    are the core of the syc and async hybrid constructs.

    Example
    ________
    def a_function()
        yield from another_function()
    @sync_generator_test
    def test_request():
        with pytest.raises(ValueError):
            yield from a_function()
    """

    @wraps(test)
    def wrapper(*args, **kwargs):
        client = gcapi.Client(token="foo")
        client._wrap_function(test)(*args, **kwargs)

    return wrapper
