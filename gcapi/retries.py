import abc


class RetryStrategy(abc.ABC):
    def get_interval_ms(self, response):
        """Returns the number of ms to pause before the next retry given the latest response"""
        pass
