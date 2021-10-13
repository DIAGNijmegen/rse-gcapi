class GCAPIError(Exception):
    """Base class for all exceptions"""


class ObjectNotFound(GCAPIError):
    """Zero objects found when one was expected"""


class MultipleObjectsReturned(GCAPIError):
    """Multiple objects returned when one was expected"""
