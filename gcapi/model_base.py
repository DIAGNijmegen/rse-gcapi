import warnings


class BaseModel:
    def __getitem__(self, key):
        self._warn_deprecated_access(key, "getting")
        return getattr(self, key)

    def __setitem__(self, key, value):
        self._warn_deprecated_access(key, "setting")
        return setattr(self, key, value)

    def __delitem__(self, key):
        self._warn_deprecated_access(key, "deleting")
        return delattr(self, key)

    @staticmethod
    def _warn_deprecated_access(key, action):
        warnings.warn(
            message=(
                f'Using ["{key}"] for {action} attributes is deprecated '
                "and will be removed in the next release. "
                f'Suggestion: Replace ["{key}"] with .{key}'
            ),
            category=DeprecationWarning,
            stacklevel=3,
        )
