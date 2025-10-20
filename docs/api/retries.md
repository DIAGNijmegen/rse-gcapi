# Retries

Sometimes API requests fail because of intermediate problems between the client and the server. These can be retried.
## Default
By default, these server-side errors (i.e. `5xx`) are retried with an exponential-backoff strategy. This entails the client waits progressively longer and longer when it encounters the same retriable error.

If the server response specifies a `"Retry-After"` header it will take precedence over any delays.

## Customize the backoff strategy
The backoff strategy is customizable by providing a simple class when initializing the client.

For instance, in this example we wait 10 seconds every time we get an error we can retry:

```Python
import gcapi
import httpx

class RetryAfterTenSeconds(gcapi.retries.BaseRetryStrategy):
    def get_delay(self, latest_response: httpx.Response):
        return 10

token = 'my-personal-api-token'
client = gcapi.Client(
            token=token,
            retry_strategy=RetryAfterTenSeconds,
        )
```
# Retries

Sometimes API requests fail in because of intermediate problems between the client and the server. These can be retried.

## Default
By default, these server-side errors (i.e. `5xx`) are retried with an exponential-backoff strategy. This entails the client waits progressively longer and longer when it encounters the same retriable error.

If the server response specifies a `"Retry-After"` header it will take precedence over any delays.

## Customize the backoff strategy
The backoff strategy is customizable by providing a simple class when initializing the client.

For instance, in this example we wait 10 seconds everytime we get an error we can retry:

```Python
import gcapi
import httpx

class RetryAfterTenSeconds(gcapi.retries.BaseRetryStrategy):
    def get_delay(self, latest_response: httpx.Response):
        return 10

token = 'my-personal-api-token'
client = gcapi.Client(
            token=token,
            retry_strategy=RetryAfterTenSeconds,
        )
```
