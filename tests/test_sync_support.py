import asyncio

import pytest

from gcapi.apibase import APIBase
from gcapi.sync_support import SyncCompatWrapperMeta


class SubAPI(APIBase):
    def __init__(self, parent):
        self.parent = parent

    async def func(self):
        await asyncio.sleep(1e-6)
        return 42

    async def func_calling_parent_api(self):
        return await self.parent()

    def __call__(self):
        return 42


class API(APIBase):
    async def func(self):
        await asyncio.sleep(1e-6)
        return 42

    async def func_calling_client(self):
        return await self.parent()

    async def func_calling_parent_func(self):
        return await self.parent.func_b()

    def __init__(self, parent):
        self.parent = parent
        self.sub_api = SubAPI(parent=parent)

    async def __call__(self):
        await asyncio.sleep(1e-6)
        return 42


class AsyncClient:
    def __init__(self):
        self.api = API(self)

    def func(self):
        return 42

    async def async_func(self) -> int:
        await asyncio.sleep(1e-6)
        return 42

    async def async_to_async_func(self):
        return await self.async_func()

    async def __call__(self):
        await asyncio.sleep(1e-6)
        return 42

    def sync_gen_func(self):
        yield from [42] * 3

    async def async_gen_func(self):
        for i in [42] * 3:
            await asyncio.sleep(1e-6)
            yield i


def test_sync_compat_calls():
    class SyncClient(AsyncClient, metaclass=SyncCompatWrapperMeta):
        pass

    client = SyncClient()

    # Regular calls
    assert client.func() == 42
    assert client.async_func() == 42
    assert client.async_to_async_func() == 42
    assert client() == 42

    # Test API methods
    assert client.api.func() == 42
    assert client.api.sub_api.func() == 42
    assert client.api.func_calling_client() == 42
    assert client.api.sub_api.func_calling_parent_api() == 42

    # Test api calls
    assert client.api() == 42  # Call async __call__ method
    assert client.api.sub_api() == 42  # Call sync __call__ method
    assert client.api.parent() == 42  # Call 'up' async __call__ method

    # Test generator methods
    assert list(client.sync_gen_func()) == [42, 42, 42]
    assert list(client.async_gen_func()) == [42, 42, 42]

    # Call another async while iterating an async_gen_func
    # Should work since the two methods spawn independent loops
    # that never run at the same time.
    all_results = []
    for i in client.async_gen_func():
        all_results.append(i)
        assert i == 42
        assert client.async_func() == 42
    assert all_results == [42, 42, 42]  # Sanity that we still got all results


@pytest.mark.anyio
async def test_sync_compat_in_existing_event_loop():
    class SyncClient(AsyncClient, metaclass=SyncCompatWrapperMeta):
        pass

    context = pytest.raises(
        RuntimeError,
        match="Cannot use the synchronous client while an event loop is running",
    )

    with context:
        SyncClient()
