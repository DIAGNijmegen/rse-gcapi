If you are working on an algorithm, you most likely want to automatically upload cases to an algorithm on the platform. This can be done via the API and most easily using the convienence method: [Client.start_algorithm_job][gcapi.client.Client.start_algorithm_job].

First things first, we need to [get started](../../getting-started.md) and initiate the client:

```Python
import gcapi
client = gcapi.Client(token="your-personal-token")
```

## Start jobs

!!! info "Job limits"
    The number of jobs running at the same time and the number jobs you are allowed to run in a set time period have [limits](https://grand-challenge.org/documentation/try-out-your-algorithm/#credits). For large processing batches these exceptions will need to be handled. One way is [using a retry strategy](../../usage/retries/handling_limits.md).


Start off by getting the algorithm details, making sure you [have access rights](../../getting-started.md#access-rights):

```Python
algorithm_slug = "your-algorithm-slug"
algorithm = client.algorithms.detail(slug=algorithm_slug)
```

Explore the inputs that the algorithm expects by visiting the Try-Out page on Grand Challenge.



Next, we will submit the inputs to the algorithm case-by-case. For this example we'll assume the algorithm requires an `ct-image` and a `lung-volume` as inputs.

```python
from gcapi import SocketValueSpec

job_1 = client.start_algorithm_job(
    algorithm_slug="your-algorithm-slug",
    inputs=[
        SocketValueSpec(socket_slug="ct-image", files=["0.dcm", "1.dcm"]),
        SocketValueSpec(socket_slug="lung-volume", value=42),
    ]
)
```

As an alternative, let us source the `ct-image` from an archive and the `lung-volume` from a local JSON file for a second job:

```python
archive_item_pk = "09e38ccd..."
archive_item = client.archive_items.details(pk=archive_item_pk)

job_2 =  client.start_algorithm_job(
    algorithm_slug="your-algorithm-slug",
    inputs=[
        SocketValueSpec(socket_slug="ct-image", existing_socket_value=archive_item.values[0]),
        SocketValueSpec(socket_slug="lung-volume", file="path/to/lung-volume.json"),
    ]
)
```

!!! tip "Tip: store the job identifiers"

    Starting a lot of jobs in sequence might benefit from storing the job identifiers in an offline manner.

    Imagine you have a collection of local CT images you are inputting:

    ```python
    import glob
    ct_images = glob.glob("*.mha")
    ```

    Storing the job identifiers in a local JSON file (e.g. `running_jobs.json`) means they can later be used to query state or download results:

    ```python
    jobs = []
    for ct_image in ct_images:
        job = client.start_algorithm_job(
            algorithm="your-algorithm-slug",
            inputs=[SocketValueSpec(socket_slug="ct-image", files=["0.dcm", "1.dcm"])],
        )
        jobs.append(job.pk)

    # Store the started jobs offline
    with open("running_jobs.json", "w") as f:
        json.dump(jobs, f, indent=2)
    ```

## Inspect jobs
After a job has ended with the status `'Succeeded'`, you can [download the outputs](../algorithm/download_algorithm_outputs.md).

Here is how to query their status:

```python
jobs = [client.algorithm_jobs.detail(job.pk) for job in jobs]
print([job.status for job in jobs])
```
