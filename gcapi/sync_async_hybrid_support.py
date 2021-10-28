"""
This module contains definitions that allow functions to expose a
"hybrid implementation" that works for classes that should expose a synchronous
or asynchronous interface.

Problem
-------

We want to support two APIs in parallel for gcapi. One synchronous and
one asynchronous API interface. Simple example:

.. code-block:: python

    import httpx

    class SyncClient(httpx.Client):
        def rest_query(self, pk):
            result = self.request(f"https://server.com/api/v1/{pk}")
            return result.json["data"]

    class AsyncClient(httpx.AsyncClient):
        async def rest_query(self, pk):
            result = await self.request(f"https://server.com/api/v1/{pk}")
            return result.json["data"]

Both of these implementations share 90% of their code, but the big difference
is the async which changes the entire way the method of the async client works
compared to the sync-client. Normally, it would be possible to abstract the
shared codebase into its own class and let both inherit from there. However,
since both the signature of the method _and_ the called function signature
(request) exposes a different interface in both cases, this is not so trivial to
solve.

Or using examples:

.. code-block:: python

    class Common:
        def rest_query(self, pk):
            result = self.request(f"https://server.com/api/v1/{pk}")
            return result.json["data"]

    class SyncClient(httpx.Client, Common):
        ''' This works fine '''

    class AsyncClient(httpx.AsyncClient, Common):
        async def rest_query(self, pk): # Redefine as async method
            return super().rest_query(pk) # ???


There are two problems with the ???-line:

 - AsyncClient.request will return immediately and return a
   coroutine. Therefore the result.json['data'] of the Common
   class does not work
 - If Common.request _would_ work, it would be synchronous
   (probably?) and not asynchronous

A similar issue arises when starting out with an async-Common class, which
ultimately boils down to "await" being unusable in synchronous methods.

Solution
--------

The only way to solve this problem and use a shared Common class is to
abstract _both_ the API-calls to httpx and the function interfaces so that
both can be specialized again in the AsyncClient and SyncClient classes. This
module contains tools that make it easy to abstracting the API calls.

The choice language feature to do so are synchronous generators. Generators
can be used to yield abstracted call descriptions to the parent which then can
execute the call and return the result of the httpx-call using the yield-result
(or generator.send). Synchronous generators allow returning function results
as well, so all features for regular functions are covered. For generators that
need to call the httpx-api, this is a bit different, and the solution to
this issue will be discussed below.

Example: Implement AsyncClient/SyncClient with Common class
-----------------------------------------------------------

As an example how this module can be used, we use the example from above.
However, one difference is that the Common-class should yield a call-description
for the underlying httpx-API and not do queries on its own anymore:

.. code-block:: python

    from gcapy.sync_async_hybrid_support import CallCapture

    class Common:
        def rest_query(self, pk):
            result = (
                yield CallCapture().request(f"https://server.com/api/v1/{pk}")
            )
            return result.json["data"]

This new implementation will create a generatorfunction "rest_query" that will
yield a CapturedCall describing how "request(f"https://server.com/api/v1/{pk}")"
should be invoked on the httpx.Client. The CapturedCall is constructed using
the CallCapture helper class. It is up to the parent to implement interpretation
of the captured call, and correctly obtain the result.

.. code-block:: python

    class SyncClient(httpx.Client, Common):
        def rest_query(self, pk):
            generator = super().rest_query(pk)
            try:
                yield_result = None
                while True:
                    call = generator.send(yield_result)
                    yield_result = call.execute(self) # Sync call!
            except StopIteration as stop:
                return stop.value

    class AsyncClient(httpx.AsyncClient, Common):
        async def rest_query(self, pk):
            generator = super().rest_query(pk)
            try:
                yield_result = None
                while True:
                    call = generator.send(yield_result)
                    yield_result = await call.execute(self) # Async call!
            except StopIteration as stop:
                return stop.value

That is it - in essence. The yielded call is executed by the parent which
knows the corresponding call signature using the CapturedCall.execute function.
We can add the await that is needed for asynchronous calls or omit it for
synchronous calls.

This is a simplified version on how gcapi does achieve sync/async support. The
full implementation is part of the gcapi-module and correctly handles
dealing with exceptions and generators as well, which make things more
complicated.

Special case: Generators
------------------------

The Common-class in the example above, technically changes its signature: All
methods become generators, and all generators become - well stay, generators.
This is not handy because the generator-invocation loops, used in the
example above for implementing AsyncClient and SyncClient, can better be
implemented as some generic function that is applied to all api-functions
of the common-class automatically.

However, because everything looks like a generatorfunction now, a generic
function like that would not know for which Common-methods to generate a
regular function signature or a generatorfunction signature.

To solve this problem, this module declares a decorator @mark_generator
that can be used to mark functions that should become actual
geneneratorfunctions in their corresponding implementations

is_generator can be used to check for the presence of this marker.

For an example how this is use, check the iterate_all() function defined
in the apibase module and the generator-driver functions defined in the gcapi
module.

"""

from typing import Callable, Dict, NamedTuple, Tuple, Union


class _CapturedCall(NamedTuple):
    func: Union[object, Callable]
    args: Tuple
    kwargs: Dict


# Paul K.: Trick to get the SLOT-constant through the mypy verification, which
# does not like extra members being added to the a NamedTuple. dataclasses
# would be the correct answer, but are not available in python 3.6 which we need
# for MeVisLab
class CapturedCall(_CapturedCall):
    """
    A "CapturedCall" is a description of a "deep call" including all arguments.
    A "deep call" is a call to a function in some complex object-hierarchy,
    like:

    `parent.child.grandchild.func("a", "b")`
    """

    SLOT = object()

    def execute(self, root):
        """
        Use this member function to execute a call using `root` as the
        new object to defer the captured call to.
        """

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


class CallCapture:
    """
    This class can be used to "capture" a call. This means, it is capturing all
    arguments for a complex member-call to a deep object structure like:

    `parent.child.grandchild.func("a", "b")`

    Capturing a call through this function, will yield a "CapturedCall", which
    can be executed in some other context using the CapturedCall.execute
    function.

    This is used to defer calling a function in hybrid sync/async functions
    to a callee which knows which interface (sync/async) to use for the call.
    """

    ref_self: Union[object, CapturedCall]

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


GENERATOR_MARKER = "__gcapi_generator"


def mark_generator(f):
    """
    All types of functions (generator or normal) that should support hybrid
    operations (sync and async) will have a generatorfunction-like signature.

    It is therefore necessary to mark generators that should get a
    generator signature anyway, with some other means. This function can be
    used as a decorator to mark those functions
    """
    setattr(f, GENERATOR_MARKER, True)
    return f


def is_generator(f):
    """
    This is the buddy of "mark_generator" and checks if a function is marked
    as a generator.
    """
    return getattr(f, GENERATOR_MARKER, False)
