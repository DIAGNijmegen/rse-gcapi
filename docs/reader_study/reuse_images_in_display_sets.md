When creating display sets for a reader study, it is sometimes the case that images are being shown multiple times in different display sets. Once uploaded, ot is beneficial to re-use the image references.

!!! tip
    Viewer applications such as CIRRUS need to **download each image** in the display set. If a display set correctly re-uses an image a viewer can re-use a previous download. This generally speeds up the case loading.

## Get an image reference

Archives, Job results and other display sets have references to already uploaded images. If you have not yet uploaded the image, you can first create a display set.

### Create the first display set
[Create a display set](../reader_study/create_display_sets.md) roughly as follows:

```Python
reader_study_slug = "my-reader-study-slug"

case = {
    "ct-image": "/path/to/image/file/00.mhd"
}

# Create a simple display set with one MHD image
display_sets = client.add_cases_to_reader_study(
    reader_study=reader_study_slug,
    values=[case]
)
```

### Wait for processing
The postprocessing of images on Grand Challenge means that we have to wait a short while until all files are processed:

```Python
import time

reader_study = client.reader_studies.detail(slug=slug)

while True:
    # Fetch the latest status of all display sets
    display_sets = client.reader_studies.display_sets.iterate_all(params={"reader_study": reader_study.pk})

    # Check if all display sets have their values processed
    if all(len(ds.values) > 0 for ds in display_sets):
        break

    # Wait a bit before checking again
    time.sleep(60)
```


### Create a new display set

Finally, when the images have been processed you can reference them when creating a new display set:

```Python

image_reference = None

# Reference the first display set, and the first value
for value in display_sets[0].values:
    if value.interface.slug == "ct-image":
        image_reference = display_sets[0].values[0].image

assert image_reference

new_case = {
    "ct-image": image_reference,
}
new_display_sets = client.add_cases_to_reader_study(
    reader_study=reader_study_slug,
    values=[new_case]
)
```
