import inspect
import logging
from functools import wraps
from typing import Any, Dict, List, AsyncGenerator

import httpx

from .apibase import APIBase
from .client import ClientBase
from .sync_async_hybrid_support import is_generator, CapturedCall

logger = logging.getLogger(__name__)


class Client(httpx.Client, ClientBase):
    def __wrap_sync(self, f):
        @wraps(f)
        def wrapped_generator(*args, **kwargs):
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

        if is_generator(f):
            return wrapped_generator
        else:

            @wraps(f)
            def wrap(*args, **kwargs):
                gen = wrapped_generator(*args, **kwargs)
                try:
                    while True:
                        gen.send(None)
                        raise ValueError(
                            "wrapped function unexpectedly yielded"
                        )
                except StopIteration as e:
                    return e.value

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
        return self.__wrap_sync(super().__call__)(*args, **kwargs)

    def upload_cases(self, *args, **kwargs):
        return self.__wrap_sync(super().upload_cases)(
            *args, **kwargs
        )

    def run_external_job(self, *args, **kwargs):
        return self.__wrap_sync(super().run_external_job)(
            *args, **kwargs
        )


class Result:
    def __init__(self, v):
        self.value = v


class AsyncClient(httpx.AsyncClient, ClientBase):
    def __wrap_sync(self, f):
        @wraps(f)
        async def wrapped_generator(*args, **kwargs):
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
                            call_result = await yld_result.execute(self)
                        else:
                            call_result = yield yld_result
                    except Exception as e:  # Yes, capture them all!
                        call_exc = e
                    else:
                        call_exc = None
            except StopIteration as stop_iteration:
                if stop_iteration.value is not None:
                    yield Result(stop_iteration.value)

        if is_generator(f):
            return wrapped_generator
        else:

            @wraps(f)
            async def wrap(*args, **kwargs):
                gen = wrapped_generator(*args, **kwargs)
                while True:
                    r = await gen.asend(None)
                    if isinstance(r, Result):
                        return r.value
                    raise ValueError("wrapped function unexpectedly yielded")

            return wrap

    def __init__(self, *args, **kwargs):
        ClientBase.__init__(self, httpx.AsyncClient, *args, **kwargs)

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

    async def __call__(self, *args, **kwargs):
        return await self.__wrap_sync(super().__call__)(
            *args, **kwargs
        )

    async def upload_cases(self, *args, **kwargs):
        return await self.__wrap_sync(super().upload_cases)(
            *args, **kwargs
        )

    async def run_external_job(self, *args, **kwargs):
        return await self.__wrap_sync(
            super().run_external_job
        )(*args, **kwargs)
