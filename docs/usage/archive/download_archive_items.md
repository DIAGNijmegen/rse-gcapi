First, start off by getting the archive object. For this you will need either the [pk, slug or api url](../../getting-started.md#on-object-identifiers) or the archive.

```python
slug = "my-archive-slug"
archive = client.archives.detail(slug=slug)
```

Then continue below to download the archive's content.

Archive items allow you to store multiple related files together. For example, you can store:
- A medical image with its segmentation mask
- An image with associated metadata (e.g., disease likelihood scores)
- Multiple images with their annotations
- Any combination of images, files, and metadata

This makes archives ideal for storing complex datasets where multiple files are logically grouped together. However, it makes downloading a bit more complex.


## Download **image-only** Archive Items

If your archive only contains images, getting them can best be done via the images API:

```python
# Get information about images in the archive from the API
images = client.images.iterate_all(
    params={'archive': archive.pk}
)

# Download images
for image in images:
    client.images.download(
        files=image.files,
        filename=Path(output_archive_dir, image.file)
    )
```

## Download **complex** Archive Items

Complex archive items contain a combination of images, values and files. Downloading all these variants is more involved.

First, get all the archive items that are in the archive:

```python
archive_items = list(
    client.archive_items.iterate_all(
        params={"archive": archive.pk}
    )
)
```

Then one-by-one, download the values found within via [Client.download_socket_value][gcapi.client.Client.download_socket_value]. The snippet below will download all the files to the `download/` directory: creating a subdirectory for each archive item.

```python
from pathlib import Path
import json

output_path = Path("download/")

for item in archive_items:
    item_path = output_path / item.pk

    item_path.mkdir(parents=True, exist_ok=True)

    for socket_value in item.values:
        client.download_socket_value(
            socket_value,
            output_directory=item_path
        )
```
