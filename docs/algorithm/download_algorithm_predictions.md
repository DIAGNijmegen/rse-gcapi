Once your Algorithm Job is in the `'Succeeded'` state you can proceed to download the predictions.

Make sure you have [gotten started](../getting-started.md) and have the algorithm object handy:

```python
algorithm = client.algorithm.detail(slug="your-algorithm-slug")
```

## List the jobs

If you've submitted all the jobs yourself, you'll likely have an array of jobs still in memory, use that:

```python
job_pks = ["618...", "5b3..."]
jobs = [client.algorithm_jobs.detail(pk=pk) for pk in job_pks]
```

Alternatively, you might need to query all the jobs of the algorithm:

```python
jobs = client.algorithm_jobs.iterate_all(
        params={"algorithm_image__algorithm": algorithm.pk},
    )
```

!!! tip "Filtering On Algorithm Image"

    The algorithm image dictates exactly which **algorithm version** was used and using it ensures we only get results from this particular version of the algorithm. Use it to filter your jobs:

    ```python
    algorithm_image_pk = "6185b379-e246-4ff3-90cf-2edc76ce0245"
    algorithm_image = client.algorithm_images.detail(pk=algorithm_image_pk)

    algorithm = client.algorithms.detail(api_url=algorithm_image.algorithm)

    jobs = client.algorithm_jobs.iterate_all(
        params={"algorithm_image__algorithm": algorithm.pk},
    )

    filtered_jobs = [job in jobs if job.algorithm_image == algorithm_image.api_url]
    ```


## Download the outputs

With a job list ready, download the outputs of the jobs by handling the socket values depending on the output socket:

```python
from pathlib import Path
import json

output_path = Path("download/")

for job in jobs:
    assert job.status == "Succeeded"

    item_path = output_path / job.pk

    item_path.mkdir(parents=True, exist_ok=True)

    for socket_value in job.outputs:
        filename = item_path / socket_value.interface.relative_path
        super_kind = socket_value.interface.super_kind.casefold()

        if super_kind == "image":
            # Image values
            client.images.download(
                url=socket_value.image,
                filename=filename
            )
        elif super_kind == "value":
            # Direct values (e.g. '42')
            with open(filename, "w") as f:
                json.dump(socket_value.value, f, indent=2)
        elif super_kind == "file":
            # Values stored as files
            resp = client(url=socket_value.file, follow_redirects=True)
            resp.raise_for_status()
            with open(filename, "wb") as f:
                f.write(resp.content)
        else:
            raise ValueError(f"Unexpected super_kind {socket_value.super_kind}")
```
