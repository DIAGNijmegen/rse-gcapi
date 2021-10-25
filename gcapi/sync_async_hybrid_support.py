"""
This module contains definitions that allow functions to expose a
"hybrid implementation" that works for classes that should expose a synchronous
or asynchrnous interface.

Problem
-------

TODO

Solution
--------

TODO
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
