import contextlib

from httpx import HTTPTransport

from tests.scripts.constants import USER_TOKENS

ADMIN_TOKEN = USER_TOKENS["admin"]
READERSTUDY_TOKEN = USER_TOKENS["readerstudy"]
DEMO_PARTICIPANT_TOKEN = USER_TOKENS["demop"]
ARCHIVE_TOKEN = USER_TOKENS["archive"]


@contextlib.contextmanager
def mock_transport_responses(transport, responses):
    """
    Mocks the responses in the provided HTTPX transport by
    shadowing the request handlers just before the HTTPTransport
     in the transport's MRO.

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
        if cls is HTTPTransport:
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
