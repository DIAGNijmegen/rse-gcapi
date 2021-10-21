import time
import asyncio
from typing import NamedTuple, Tuple, Dict, Callable


class SyncBase:
    def sleep(self, t):
        print("Sync sleep")
        time.sleep(t)

    def get_result(self):
        self.sleep(0.1)
        return "the sync result"


class AsyncBase:
    async def sleep(self, t):
        print("Async sleep")
        await asyncio.sleep(t)

    async def get_result(self):
        await self.sleep(0.1)
        return "the async result"


class CapturedCall(NamedTuple):
    func: Callable
    args: Tuple
    kwargs: Dict

    def execute(self, root):
        def sub(x):
            if x is CapturedCall.SLOT:
                return root
            elif isinstance(x, CapturedCall):
                return x.execute(root)
            else:
                return x

        func = sub(self.func)
        args = [sub(x) for x in self.args]
        kwargs = {k: sub(v) for k, v in self.kwargs.items()}
        return func(*args, **kwargs)


CapturedCall.SLOT = object()


class CallCapture:
    def __init__(self, ref_self=CapturedCall.SLOT):
        self.ref_self = ref_self

    def __getattr__(self, item):
        return CallCapture(
            CapturedCall(func=getattr, args=(self.ref_self, item), kwargs={})
        )

    def __getitem__(self, item):
        return CallCapture(
            CapturedCall(
                func=lambda a, b: a[b], args=(self.ref_self, item), kwargs={}
            )
        )

    def __call__(self, *args, **kwargs):
        return CapturedCall(func=self.ref_self, args=args, kwargs=kwargs)


class Common:
    parent: SyncBase

    def do_something(self):
        print("First getting the result")
        result = yield self.parent.get_result()
        print("Now sleeping a bit")
        yield self.parent.sleep(1)
        print("Now returning result")
        return result


class Sync(SyncBase):
    def __init__(self):
        self.common = Common()
        self.common.parent = CallCapture()

    def sync_call(self):
        sync_base = SyncBase()
        execution = self.common.do_something()
        try:
            for call in execution:  # type: CapturedCall
                try:
                    result = call.execute(sync_base)
                except Exception as e:
                    execution.throw(e)
                else:
                    execution.send(result)
        except StopIteration as e:
            return e.value
        except Exception as e:
            execution.throw(e)


class Async(AsyncBase):
    def __init__(self):
        self.common = Common()
        self.common.parent = CallCapture()

    async def async_call(self):
        async_base = AsyncBase()
        execution = self.common.do_something()
        try:
            for call in execution:  # type: CapturedCall
                try:
                    result = await call.execute(async_base)
                except Exception as e:
                    execution.throw(e)
                else:
                    execution.send(result)
        except StopIteration as e:
            return e.value


if __name__ == "__main__":
    print("=== Testing async loop")
    el = asyncio.get_event_loop()
    el.run_until_complete(Async().async_call())

    print("=== Testing sync loop")
    Sync().sync_call()
