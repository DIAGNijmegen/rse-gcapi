from httpx import HTTPStatusError
from time import sleep


def recurse_call(func):
    def wrapper(*args, **kwargs):
        for _ in range(60):
            try:
                result = func(*args, **kwargs)
                break
            except (HTTPStatusError, ValueError):
                sleep(0.5)
        else:
            raise TimeoutError
        return result

    return wrapper


def async_recurse_call(func):
    async def wrapper(*args, **kwargs):
        for _ in range(60):
            try:
                result = await func(*args, **kwargs)
                break
            except (HTTPStatusError, ValueError):
                sleep(0.5)
        else:
            raise TimeoutError
        return result

    return wrapper
