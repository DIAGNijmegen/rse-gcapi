import inspect
import logging
from functools import wraps

import httpx

from .apibase import APIBase
from .client import ClientBase

logger = logging.getLogger(__name__)


class Client(ClientBase, httpx.Client):
    def __wrap_sync(self, f):
        @wraps(f)
        def wrap(*args, **kwargs):
            calls = f(*args, **kwargs)
            try:
                call_result = None
                call_exc = None
                while True:
                    if call_exc:
                        yld_result = calls.throw(call_exc)
                    else:
                        yld_result = calls.send(call_result)
                    try:
                        call_result = yld_result.execute(self)
                    except Exception as e:  # Yes, capture them all!
                        call_exc = e
                    else:
                        call_exc = None
            except StopIteration as stop_iteration:
                return stop_iteration.value

        return wrap

    def __init__(self, *args, **kwargs):
        ClientBase.__init__(self, httpx.Client, *args, **kwargs)

        def wrap_api(api: APIBase):
            for name in dir(api):
                if name.startswith("__"):
                    continue
                item = getattr(api, name)
                if inspect.isgeneratorfunction(item):
                    setattr(api, name, self.__wrap_sync(item))
            for sub_api_name in api.sub_apis:
                wrap_api(getattr(api, sub_api_name))

        for api_name in self._api_meta.__annotations__.keys():
            wrap_api(getattr(self._api_meta, api_name))

    def __call__(self, *args, **kwargs):
        return self.__wrap_sync(super(Client, self).__call__)(*args, **kwargs)


class AsyncClient:
    pass
