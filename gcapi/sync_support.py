import asyncio
import inspect
import threading

from gcapi.apibase import APIBase


def is_async_callable(obj):
    """Checks for async methods but also hits async __call__ methods"""
    if inspect.iscoroutinefunction(obj):
        return True
    else:
        try:
            call_method = obj.__call__
        except AttributeError:
            return False
        else:
            return inspect.iscoroutinefunction(call_method)


def assert_not_in_running_loop():
    """
    When in a running asynchronous context, we present an informative error message.
    """
    try:
        event_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        if event_loop.is_running():
            raise RuntimeError(
                "Cannot use the synchronous client while an event loop is running. "
                "Please use the asynchronous client in an asynchronous context."
            )


class SyncCompatWrapper:
    """
    A wrapper for an asynchronous instance that allows synchronous access
    to its methods.

    Does not work in an already running event loop context. Sorry!

    Usage:
    ```python
        async_instance = AsyncClient()
        sync_instance = SyncCompatWrapper(async_instance=async_instance)

        sync_result = sync_instance.some_async_method()
    ```
    """

    def __init__(self, *, async_instance, lock=None):
        assert_not_in_running_loop()

        self.__async_instance = async_instance
        self.__wrapping_lock = lock or threading.Lock()

    def __wrap_async_callable(self, /, func):
        def wrapper(*args, **kwargs):
            with self.__wrapping_lock:
                coro = func(*args, **kwargs)
                return asyncio.run(coro)

        return wrapper

    def __wrap_async_gen_function(self, /, func):
        def wrapper(*args, **kwargs):
            aiter = func(*args, **kwargs)
            while True:
                try:
                    sync_func = self.__wrap_async_callable(aiter.__anext__)
                    yield sync_func()
                except StopAsyncIteration:
                    self.__wrap_async_callable(aiter.aclose)()
                    break

        return wrapper

    def __getattr__(self, name):
        attr = getattr(self.__async_instance, name)

        if self.__wrapping_lock.locked():
            # We're in an intentionally asynchronous context,
            # so we return the attribute
            return attr
        elif isinstance(attr, APIBase):
            return SyncCompatWrapper(
                async_instance=attr, lock=self.__wrapping_lock
            )
        elif is_async_callable(attr):
            return self.__wrap_async_callable(attr)
        elif inspect.isasyncgenfunction(attr):
            return self.__wrap_async_gen_function(attr)
        elif isinstance(attr, APIBase):
            return SyncCompatWrapper(
                async_instance=attr, lock=self.__wrapping_lock
            )
        else:
            return attr

    def __call__(self, *args, **kwargs):
        if is_async_callable(self.__async_instance):
            sync_func = self.__wrap_async_callable(self.__async_instance)
        else:
            sync_func = self.__async_instance

        return sync_func(*args, **kwargs)


class SyncCompatWrapperMeta(type):
    """
    A metaclass that wraps the instance of a class in a `SyncCompatWrapper`

    Usage:
    ```python
        class MySyncClass(MyAsyncClass, metaclass=SyncCompatWrapperMeta):
            async def some_async_method(self):
                return await self._some_internal_async_method()

        my_sync_instance = MySyncClass()
        sync_result = my_sync_instance.some_async_method()
    ```
    """

    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        return SyncCompatWrapper(async_instance=instance)
