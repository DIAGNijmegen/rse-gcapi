from typing import Callable, Dict, NamedTuple, Tuple, Union


class _CapturedCall(NamedTuple):
    func: Union[object, Callable]
    args: Tuple
    kwargs: Dict


# Paul K.: Trick to get the SLOT-constant through the mypy verification, which
# does not like extra members being added to the a NamedTuple. dataclasses
# would be the correct answer, but are not availabe in python 3.6 which we need
# for MeVisLab
class CapturedCall(_CapturedCall):
    SLOT = object()

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


class CallCapture:
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


# Thanks to https://stackoverflow.com/questions/34073370/best-way-to-receive-
# the-return-value-from-a-python-generator
"""class CaptureResults:
    def __init__(self, gen):
        self.gen = gen

    def __iter__(self):
        self.result = yield from self.gen
"""
