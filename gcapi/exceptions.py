class GCAPIError(Exception):
    """Base class for all exceptions"""


class ObjectNotFound(GCAPIError):  # noqa: N818
    """Zero objects found when one was expected"""


class SocketNotFound(ObjectNotFound):  # noqa: N818
    """A socket could not be found when one was expected"""

    def __init__(self, *args, slug, **kwargs):
        super().__init__(*args, **kwargs)
        self.slug = slug


class MultipleObjectsReturned(GCAPIError):  # noqa: N818
    """Multiple objects returned when one was expected"""
