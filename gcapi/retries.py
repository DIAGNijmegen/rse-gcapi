import abc


class RetryStrategy(abc.ABC):
    def get_interval(self, response):
        """
        Returns the number of seconds to pause before the next retry, based on the latest response.

        Optionally, if None is returned no retry is to be performed.
        """
        pass
