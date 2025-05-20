import inspect
import logging
from collections.abc import AsyncGenerator, Generator
from functools import wraps
from typing import Any, Callable, NamedTuple, Union

import httpx

from .apibase import APIBase
from .client import ClientBase
from .sync_async_hybrid_support import CapturedCall, is_generator
from .transports import AsyncRetryTransport, RetryTransport

logger = logging.getLogger(__name__)


class AsyncResult(NamedTuple):
    """
    Async generator functions _cannot_ return a result like synchronous
    generators can. Therefore, we use this wrapper class to wrap returned
    results and _yield_ them instead. The parent can pick up these marked
    values and return them as result instead.
    """

    value: Any


class WrapApiInterfaces(ClientBase):
    def _wrap_generator(
        self, f
    ) -> Callable[..., Union[Generator, AsyncGenerator]]:
        raise NotImplementedError()

    def _wrap_function(self, f) -> Callable:
        wrapped_generator = self._wrap_generator(f)

        if is_generator(f):
            return wrapped_generator
        elif inspect.isasyncgenfunction(wrapped_generator):

            @wraps(f)
            async def wrap(*args, **kwargs):
                gen = wrapped_generator(*args, **kwargs)
                while True:
                    r = await gen.asend(None)
                    if isinstance(r, AsyncResult):
                        return r.value
                    raise ValueError("wrapped function unexpectedly yielded")

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

    def _wrap_client_base_interfaces(self):
        def wrap_api(api: APIBase):
            attrs: dict[str, Any] = {"__init__": lambda *_, **__: None}

            for name in dir(api):
                if name.startswith("__"):
                    continue
                item = getattr(api, name)
                if inspect.isgeneratorfunction(item):
                    attrs[name] = staticmethod(self._wrap_function(item))
                else:
                    attrs[name] = item
            for sub_api_name in api.sub_apis:
                attrs[sub_api_name] = wrap_api(getattr(api, sub_api_name))
            return type(
                f"SyncWrapped{type(api).__name__}", (type(api),), attrs
            )

        for api_name in self._api_meta.__annotations__.keys():
            wrapped = wrap_api(getattr(self._api_meta, api_name))
            setattr(self._api_meta, api_name, wrapped)


class Client(httpx.Client, WrapApiInterfaces, ClientBase):
    def _wrap_generator(self, f):
        @wraps(f)
        def result(*args, **kwargs):
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

        return result

    def __init__(self, *args, **kwargs):
        ClientBase.__init__(
            self, httpx.Client, RetryTransport, *args, **kwargs
        )
        self._wrap_client_base_interfaces()

    def __call__(self, *args, **kwargs):
        return self._wrap_function(super().__call__)(*args, **kwargs)

    def upload_cases(self, *args, **kwargs):
        return self._wrap_function(super().upload_cases)(*args, **kwargs)

    def run_external_job(self, *args, **kwargs):
        return self._wrap_function(super().run_external_job)(*args, **kwargs)

    def add_cases_to_archive(self, *args, **kwargs):
        return self._wrap_function(super().add_cases_to_archive)(
            *args, **kwargs
        )

    def update_archive_item(self, *args, **kwargs):
        return self._wrap_function(super().update_archive_item)(
            *args, **kwargs
        )

    def add_cases_to_reader_study(self, *args, **kwargs):
        return self._wrap_function(super().add_cases_to_reader_study)(
            *args, **kwargs
        )

    def update_display_set(self, *args, **kwargs):
        return self._wrap_function(super().update_display_set)(*args, **kwargs)


class AsyncClient(httpx.AsyncClient, WrapApiInterfaces, ClientBase):
    def _wrap_generator(self, f):
        @wraps(f)
        async def result(*args, **kwargs):
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
                    yield AsyncResult(stop_iteration.value)

        return result

    def __init__(self, *args, **kwargs):
        ClientBase.__init__(
            self, httpx.AsyncClient, AsyncRetryTransport, *args, **kwargs
        )
        self._wrap_client_base_interfaces()

    async def __call__(self, *args, **kwargs):
        return await self._wrap_function(super().__call__)(*args, **kwargs)

    async def upload_cases(self, *args, **kwargs):
        return await self._wrap_function(super().upload_cases)(*args, **kwargs)

    async def run_external_job(self, *args, **kwargs):
        return await self._wrap_function(super().run_external_job)(
            *args, **kwargs
        )

    async def add_cases_to_archive(self, *args, **kwargs):
        return await self._wrap_function(super().add_cases_to_archive)(
            *args, **kwargs
        )

    async def update_archive_item(self, *args, **kwargs):
        return await self._wrap_function(super().update_archive_item)(
            *args, **kwargs
        )

    async def add_cases_to_reader_study(self, *args, **kwargs):
        return await self._wrap_function(super().add_cases_to_reader_study)(
            *args, **kwargs
        )

    async def update_display_set(self, *args, **kwargs):
        return await self._wrap_function(super().update_display_set)(
            *args, **kwargs
        )
