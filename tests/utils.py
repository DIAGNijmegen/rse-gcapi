import contextlib
from time import sleep

from httpx import AsyncHTTPTransport, HTTPStatusError, HTTPTransport

ADMIN_TOKEN = "1b9436200001f2eaf57cd77db075cbb60a49a00a"
READERSTUDY_TOKEN = "01614a77b1c0b4ecd402be50a8ff96188d5b011d"
DEMO_PARTICIPANT_TOKEN = "00aa710f4dc5621a0cb64b0795fbba02e39d7700"
ARCHIVE_TOKEN = "0d284528953157759d26c469297afcf6fd367f71"


def recurse_call(func):
    def wrapper(*args, **kwargs):
        for _ in range(60):
            try:
                result = func(*args, **kwargs)
                break
            except (HTTPStatusError, ValueError):
                sleep(0.5)
        else:
            raise TimeoutError
        return result

    return wrapper


def async_recurse_call(func):
    async def wrapper(*args, **kwargs):
        for _ in range(60):
            try:
                result = await func(*args, **kwargs)
                break
            except (HTTPStatusError, ValueError):
                sleep(0.5)
        else:
            raise TimeoutError
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
