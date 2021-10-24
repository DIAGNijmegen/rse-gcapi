import inspect
import logging
from functools import wraps
from typing import Any, Dict, List

import httpx

from .apibase import APIBase
from .client import ClientBase
from .sync_async_hybrid_support import is_generator, CapturedCall

logger = logging.getLogger(__name__)


class Client(httpx.Client, ClientBase):
    def __wrap_sync(self, f):
        if is_generator(f):

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
                            if isinstance(yld_result, CapturedCall):
                                call_result = yld_result.execute(self)
                            else:
                                call_result = yield yld_result
                        except Exception as e:  # Yes, capture them all!
                            call_exc = e
                        else:
                            call_exc = None
                except StopIteration as stop_iteration:
                    return stop_iteration.value

        else:

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
            attrs: Dict[str, Any] = {"__init__": lambda *_, **__: None}

            for name in dir(api):
                if name.startswith("__"):
                    continue
                item = getattr(api, name)
                if inspect.isgeneratorfunction(item):
                    attrs[name] = staticmethod(self.__wrap_sync(item))
                else:
                    attrs[name] = item
            for sub_api_name in api.sub_apis:
                attrs[sub_api_name] = wrap_api(getattr(api, sub_api_name))
            return type(
                f"SyncWrapped{type(api).__name__}", (type(api),), attrs
            )

        for api_name in self._api_meta.__annotations__.keys():
            wrapped = wrap_api(getattr(self._api_meta, api_name))
            setattr(
                self._api_meta, api_name, wrapped,
            )

    def __call__(self, *args, **kwargs):
        return self.__wrap_sync(super(Client, self).__call__)(*args, **kwargs)

    def upload_cases(self, *args, **kwargs):
        return self.__wrap_sync(super(Client, self).upload_cases)(
            *args, **kwargs
        )

    def run_external_job(self, *args, **kwargs):
        return self.__wrap_sync(super(Client, self).run_external_job)(
            *args, **kwargs
        )


class AsyncClient:
    pass
