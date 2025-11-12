If you are working on a challenge, you most likely need to upload cases to an archive on the platform. This can be done via the API and most easily using the convienence method: [Client.add_case_to_archive][gcapi.client.Client.add_case_to_archive], together with one or more [SocketValueSpec][gcapi.SocketValueSpec]s.

First things first, we need to [get started](../../getting-started.md) and initiate the client:

```Python
import gcapi
client = gcapi.Client(token="your-personal-token")
```


## Example
For this particular example, the data on your machine would be structured as follows:

```bash
mainfolder/
├── patient1_folder
│		├──file_for_a_single_series
├── patient2_folder
│		├──file_for_a_single_series
├──patient3_folder
│		├──file_for_a_single_series
          ...
├──patientN_folder
│		├──file_for_a_single_series
```

Lets now list the files in the upload directory:
```python
# Specify the directory path which you want to upload from.
upload_from_dir = Path(r"path/on/your/machine/with/data/for/archive")

# Create list of files in the specified directory.
files = sorted(f for f in upload_from_dir.rglob("*.*") if f.is_file())
print("Found", len(files), "cases for upload")
```


## Create archive items

An Archive contains Archive Items. An archive item consists of one or more socket values, which can be images, files or other data. To create archive items for the algorithms to predict on, you need to provide a [socket slug](https://grand-challenge.org/documentation/interfaces/) for each socket value. Within an archive item, a socket slug needs to be unique. For example, one cannot have three `generic-medical-images` within a single archive item.

In this example two archive items are created and each archive item contains three sockets, with slugs: a `ct-image`, an `airway-segmentation` and `some-score`.

!!! tip "Challenge Sockets"
    For archives that are linked to challenges, the sockets will need to correspond to the sockets that have been configured as input for the challenge algorithms. For an overview of these sockets, visit the submit page(s) of your challenge.


```python
from gcapi import SocketValueSpec

cases = [
    [
        SocketValueSpec(socket_slug="ct-image", files=files[0:2]),
        SocketValueSpec(socket_slug="airway-segmentation", file=files[2]),
        SocketValueSpec(socket_slug="some-score", value=2.1),
    ],
    [
        SocketValueSpec(socket_slug="ct-image", files=files[3:5]),
        SocketValueSpec(socket_slug="airway-segmentation", file=files[5]),
        SocketValueSpec(socket_slug="some-score", value=7.9),
    ],
    ...
]
```

To upload cases and create the archive items, you will need to know the [slug](../../getting-started.md#slugs) of the particular archive you will work with.

```python
# Specify the "slug" of the archive you want to upload your data to.
upload_archive_slug = "my-archive-slug"

archive_items = []
for case in cases:
    archive_item = client.add_case_to_archive(
        archive_slug=upload_archive_slug,
        values=case,
    )
    archive_items.append(archive_item)
print("Uploaded cases and created archive items: " + archive_items)
```

!!! info "Upload limits"
    The number of yet unprocessed user uploads have limits. For large processing batches these exceptions will need to be handled. One way is [using a retry strategy](../../usage/retries/handling_limits.md).
