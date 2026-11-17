import contextlib
import io
import json as json_module
from http import HTTPStatus

import requests
from requests.adapters import HTTPAdapter

from tests.scripts.constants import USER_TOKENS

ADMIN_TOKEN = USER_TOKENS["admin"]
READERSTUDY_TOKEN = USER_TOKENS["readerstudy"]
DEMO_PARTICIPANT_TOKEN = USER_TOKENS["demop"]
ARCHIVE_TOKEN = USER_TOKENS["archive"]


def make_response(*, status_code, headers=None, json=None):
    """Builds a requests.Response without performing any request."""
    response = requests.Response()
    response.status_code = int(status_code)
    response.reason = HTTPStatus(status_code).phrase
    response.raw = io.BytesIO()
    response.headers.update(headers or {})
    if json is not None:
        response._content = json_module.dumps(json).encode()
    else:
        response._content = b""
    return response


@contextlib.contextmanager
def mock_adapter_responses(adapter, responses):
    """
    Mocks the responses in the provided requests adapter by
    shadowing the send method just before the HTTPAdapter
    in the adapter's MRO.

    Returns a class from which some metadata about the mocking can
    be read (such as number of requests).
    """
    responses = iter(responses)

    class ResponseMetaData:
        num_requests = 0

    class MockAdapter:
        @staticmethod
        def send(request, *_, **__):
            try:
                ResponseMetaData.num_requests += 1
                response = responses.__next__()
                response.request = request
                return response
            except StopIteration as e:
                raise RuntimeError("Ran out of mock responses") from e

    bases = []
    for cls in adapter.__class__.mro():
        if cls is HTTPAdapter:
            bases.append(MockAdapter)
        bases.append(cls)
    old_class = adapter.__class__
    new_class = type(
        old_class.__name__,
        tuple(bases),
        dict(old_class.__dict__),
    )
    try:
        adapter.__class__ = new_class
        yield ResponseMetaData
    finally:
        adapter.__class__ = old_class
