To start an algorithm endpoint for algorithm invocations, you must first create the endpoint. Once it is running, you
most likely want to automatically upload your inputs to the platform. This can be done via the API and most easily using
the convenience method: [Client.invoke_algorithm_endpoint][gcapi.client.Client.invoke_algorithm_endpoint].

To [get started](../../getting-started.md), initiate the client:

```Python
import gcapi
client = gcapi.Client(token="your-personal-token")
```

## Create an algorithm endpoint

First, retrieve the algorithm details, making sure you [have access rights](../../getting-started.md#access-rights):

```Python
algorithm_slug = "your-algorithm-slug"
algorithm = client.algorithms.detail(slug=algorithm_slug)
```

Create an endpoint for the algorithm:

```python
endpoint = client.algorithm_endpoints.create(algorithm=algorithm.api_url)
```

The endpoint will be started automatically. It may take a few minutes before the endpoint is ready to receive
invocations. Poll the endpoint status until it reaches the `'Running'` state using the
[detail method][gcapi.client.AlgorithmEndpointsAPI.detail]:

```python
endpoint = client.algorithm_endpoints.detail(pk=endpoint.pk)
print(endpoint.status)
```

If you no longer have the endpoint's pk, you can find the endpoint again by filtering on its status (`'Queued'`,
`'Started'` or `'Running'`):

```python
endpoint = client.algorithm_endpoints.detail(status="Running")
print(endpoint.pk)
```

### Keep the endpoint alive

Endpoints are automatically cleaned up when their lifetime expires. Each time an endpoint is invoked, its lifetime is
extended for at least the expected duration of the invocation. To keep an endpoint alive between invocations, use the
`keep_alive` method:

```python
client.algorithm_endpoints.keep_alive(pk=endpoint.pk)
endpoint = client.algorithm_endpoints.detail(pk=endpoint.pk)
print(endpoint.remaining_lifetime)
```

This extends the endpoint lifetime to 5 minutes from the time the method is called. To keep the endpoint alive, call
this method again before those 5 minutes expire.

## Invoke the endpoint

Next, submit the inputs to the algorithm for processing. For this example, we'll assume the algorithm requires a
`ct-image` and a `lung-volume` as inputs.

```python
from gcapi import SocketValueSpec

invocation = client.invoke_algorithm_endpoint(
    endpoint_pk=endpoint.pk,
    inputs=[
        SocketValueSpec(socket_slug="ct-image", files=["0.dcm", "1.dcm"]),
        SocketValueSpec(socket_slug="lung-volume", value=42),
    ]
)
```

The client first uploads the files and values to the platform for ingestion. Once ingestion is complete, the inputs are
sent to the algorithm. If the data is already available as a socket value, the uploading and ingestion can be skipped.
For example, if the `ct-image` already exists in an archive, you can reuse the existing socket value instead of
uploading it again:

```python
archive_item_pk = "09e38ccd..."
archive_item = client.archive_items.detail(pk=archive_item_pk)

invocation = client.invoke_algorithm_endpoint(
    endpoint_pk=endpoint.pk,
    inputs=[
        SocketValueSpec(socket_slug="ct-image", existing_socket_value=archive_item.values[0]),
        SocketValueSpec(socket_slug="lung-volume", value=42),
    ]
)
```

## Inspect invocations

Retrieve the invocation status using the [detail method][gcapi.client.AlgorithmInvocationsAPI.detail]:

```python
invocation = client.algorithm_invocations.detail(pk=invocation.pk)
print(invocation.status)
```

Once the invocation reaches the `'Succeeded'` state, you can [download the outputs](../algorithm/download_algorithm_outputs.md).
