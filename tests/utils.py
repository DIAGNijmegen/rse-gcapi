import contextlib
from time import sleep

from httpx import HTTPStatusError, BaseTransport, AsyncBaseTransport


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
def mock_base_transport_responses(
    transport, mock_responses, asynchronous=False
):
    mock_responses = iter(mock_responses)
    shadow_base_class = (
        BaseTransport if not asynchronous else AsyncBaseTransport
    )

    class ResponseMetaData:
        num_requests = 0

    class MockTransport:
        @staticmethod
        def handle_request(request, *_, **__):
            try:
                ResponseMetaData.num_requests += 1
                response = mock_responses.__next__()
                response.request = request
                return response
            except StopIteration:
                raise RuntimeError("Ran out of mock responses")

        async def handle_async_request(self, *args, **kwargs):
            return self.handle_request(*args, **kwargs)

    bases = []
    for cls in transport.__class__.mro():
        if cls is shadow_base_class:
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
