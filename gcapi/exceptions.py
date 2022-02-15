class GCAPIError(Exception):
    """Base class for all exceptions"""


class ObjectNotFound(GCAPIError):  # noqa: N818
    """Zero objects found when one was expected"""


class MultipleObjectsReturned(GCAPIError):  # noqa: N818
    """Multiple objects returned when one was expected"""
