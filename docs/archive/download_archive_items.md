First, start off by getting the archive object. For this you will need either the [pk, slug or api url](../getting-started.md#on-object-identifiers) or the archive.

```python
slug = "my-archive-slug"
archive = client.archives.detail(slug=slug)
```

Then download the content, which depends on the kinds of content. In the simplest case, an archive item consists of just one medical image.

Archive items, however, also allow you to store metadata or additional images, like an overlay, along with each image. An archive item could, for example, consist of a medical image and a segmentation map for the image, or a specific disease likelihood score as metadata or a combination of all of these.


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


Then one-by-one, download the values found within:

```python
from pathlib import Path
import json

output_path = Path("download/")

for item in archive_items:
    item_path = output_path / item.pk

    item_path.mkdir(parents=True, exist_ok=True)

    for socket_value in item.values:
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
