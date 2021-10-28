import asyncio

import pytest

from gcapi import AsyncClient, Client
from gcapi.gcapi import WrapApiInterfaces
from gcapi.sync_async_hybrid_support import CallCapture, mark_generator


class AbstractBase:
    def return_hello_world(self) -> str:
        ...

    def throw_value_error(self):
        ...


class SyncBase(AbstractBase):
    def return_hello_world(self):
        return "hello world"

    def throw_value_error(self):
        raise ValueError("hello world")


class AsyncBase(AbstractBase):
    async def return_hello_world(self):
        # Include async sleeping to do some async stuff. Wait must be
        # > 0, otherwise special handling kicks in. We want to test the full
        # asyncio stack though, so 0.1 it is
        await asyncio.sleep(0.1)
        return "hello world"

    async def throw_value_error(self):
        # Include async sleeping to do some async stuff. Wait must be
        # > 0, otherwise special handling kicks in. We want to test the full
        # asyncio stack though, so 0.1 it is
        await asyncio.sleep(0.1)
        raise ValueError("hello world")


class Common:
    yield_call: AbstractBase

    @mark_generator
    def generator_func(self):
        yield (yield self.yield_call.return_hello_world())
        yield (yield self.yield_call.return_hello_world())

    @mark_generator
    def func_returning_generator(self):
        return self.generator_func()

    def do_hello_world(self):
        return "DID: " + (yield self.yield_call.return_hello_world())

    def do_throw(self):
        yield self.yield_call.throw_value_error()


def test_sync():
    class Sync(WrapApiInterfaces, Common, SyncBase):
        _wrap_generator = Client._wrap_generator
        _common: Common

        def __init__(self):
            SyncBase.__init__(self)
            # We will _not_ use the WrapApiInterfaces-__init__ method!

            self._common = Common()
            for name in dir(Common):
                if name.startswith("_"):
                    continue
                item = getattr(self._common, name)
                if callable(item):
                    setattr(self, name, self._wrap_function(item))
            self._common.yield_call = CallCapture()

    sync_obj = Sync()
    assert sync_obj.do_hello_world() == "DID: hello world"
    assert [x for x in sync_obj.generator_func()] == ["hello world"] * 2
    assert [x for x in sync_obj.func_returning_generator()] == [
        "hello world"
    ] * 2


@pytest.mark.anyio
async def test_async():
    class Async(WrapApiInterfaces, Common, AsyncBase):
        _wrap_generator = AsyncClient._wrap_generator
        _common: Common

        def __init__(self):
            AsyncBase.__init__(self)
            # We will _not_ use the WrapApiInterfaces-__init__ method!

            self._common = Common()
            for name in dir(Common):
                if name.startswith("_"):
                    continue
                item = getattr(self._common, name)
                if callable(item):
                    setattr(self, name, self._wrap_function(item))
            self._common.yield_call = CallCapture()

    async_obj = Async()
    assert await async_obj.do_hello_world() == "DID: hello world"
    assert [x async for x in async_obj.generator_func()] == ["hello world"] * 2
    assert [x async for x in async_obj.func_returning_generator()] == [
        "hello world"
    ] * 2


@pytest.mark.anyio
async def test_sync_in_async():
    """
    Why this test? This test installs a event_loop but will call the
    synchronous tests. Installing an eventloop can lead to unexpected results
    with some sync->async utilities that are out there. This is mainly added as
    a sanity check. Since we do not use those tools, it is principally not
    needed, but if we want to rewrite the framework with such a tool, this
    becomes an important test!
    """
    test_sync()
