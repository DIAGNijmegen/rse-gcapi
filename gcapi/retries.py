class BaseRetries:
    def get_delay(self, latest_response):
        """
        Returns the number of seconds to pause before the next retry, based on the latest response.

        Optionally, if None is returned no retry is to be performed.
        """
        raise NotImplementedError(
            "The 'get_delay' method must be implemented."
        )
