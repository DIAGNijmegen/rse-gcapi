If you are working on a reader study, you most likely need to upload the cases to the platform. This can be done via the API and most easily using the convienence method: `Client.add_cases_to_reader_study`.

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

Lets now list the files in the upload directory to check whether they can be identified:
```python
# Specify the directory path which you want to upload from.
upload_from_dir = Path(r"path/on/your/machine/with/data/for/reader/study")

# Create list of files in the specified directory.
files = sorted(f for f in upload_from_dir.rglob("*.*") if f.is_file())
print("Found", len(files), "cases for upload")
```


## Create display sets

To create display sets for the readers to view, you need to provide a [socket](https://grand-challenge.org/documentation/interfaces/) for each image. Within a display set, a socket needs to be unique. For example, one cannot have three `ct-image` within a single display set.

!!! tip Custom Socket Creation
     If your desired socket does not yet exist, please email [support@grand-challenge.org](mailto:support@grand-challenge.org) with a title and description to add it to the [list](https://grand-challenge.org/components/interfaces/reader-studies/).

In this example two sets are created and the display set contains three sockets: a `ct-image`, an `airway-segmentation` and `some-score`:

```python
display_sets = [
    {
        "ct-image": files[0],
        "airway-segmentation": files[1],
        "some-score": 2.1,
    },
    {
        "ct-image": files[2],
        "airway-segmentation": files[3],
        "some-score": 7.9,
    },
    ...
]
```

To upload cases and create the display sets, you will need to know the [slug](../../getting-started.md#slugs) of the particular reader study you will work with.

```python
# Specify the "slug" of the study you want to upload your data to.
upload_reader_study_slug = "my-reader-study-slug"

display_set_pks = client.add_cases_to_reader_study(
  reader_study=upload_reader_study_slug,
  display_sets=display_sets
)
print("Uploaded cases and created display sets: " + display_set_pks)
```

## Setting title and order

Titles and order can easiest be set by [updating the display sets](../reader_study/update_display_sets.md#update-the-content-of-display-sets).
