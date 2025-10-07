### Using the API for algorithms

In this tutorial we will focus on how to interact with algorithms through the API. Specifically, we will show you how to:

1. [Upload input to an algorithm for inference](#upload-input-to-an-algorithm-for-inference)
2. [Download inference results from an algorithm](#download-inferenced-image-results-from-an-algorithm)
3. [Upload multiple inputs to an algorithm for inference](#upload-multiple-inputs-to-an-algorithm-for-inference)
4. [Download the results of an algorithm that produces multiple outputs](#download-the-results-of-an-algorithm-that-produces-multiple-outputs)

Remember that you need to **request access** prior to using an algorithm. You do not need to request permission if you are using your own algorithm.

If you haven't installed gcapi yet, follow the instructions [here](/documentation/what-can-gc-api-be-used-for/).

Import necessary libraries

```python
import gcapi
from pathlib import Path
from tqdm import tqdm
import SimpleITK as sitk
import numpy as np
```

Authenticate to Grand Challenge using your personal [API token](/documentation/what-can-gc-api-be-used-for/).

```python
# authorise with your personal token
my_personal_gcapi_token = 'my-personal-gcapi-token'
client = gcapi.Client(token=my_personal_gcapi_token)
```




#### Upload input to an algorithm for inference

In this section, we will use [Pulmonary Lobe Segmentation](/algorithms/pulmonary-lobe-segmentation/) by Weiyi Xie. This algorithm segments pulmonary lobes of a given chest CT scan. The algorithm uses a contextual two-stage U-Net architecture. We will use example chest CT scans from [coronacases.org](coronacases.org). They are anonymized.

First, we will retrieve the algorithm and inspect what inputs it expects.

```python
# retrieve the algorithm, providing a slug
algorithm_1 = client.algorithms.detail(slug="pulmonary-lobe-segmentation")

# explore, which input the algorithm expects
algorithm_1.interfaces
```

Next, we will submit the inputs to the algorithm one by one.
Grand Challenge creates a job instance for each set of inputs. To create a job instance use the following command:

```python
job = client.run_external_job(
    algorithm="slug-of-the-algorithm",
    inputs={
        # Some examples:
        "socket-slug0": [ "0.dcm", "1.dcm" ],
        "socket-slug1": "0.dcm",
        "socket-slug2": pathlib.Path("0.dcm"),
        "socket-slug3": pathlib.Path("0.mha"),
        "socket-slug4": 42,
        "socket-slug5": "contains-42.json",
        "socket-slug6": archive_item.values[0],
    }
)
```
- `algorithm` expects the slug of the algorithm you want to use as a string and
- `inputs` expects a dictionary with socket slugs as keys and the corresponding values in various formats

```python
# get the path to the files
files = ["io/case01.mha", "io/case02.mha"]
#timeout
jobs = []

# submit a job for each file in your file list
for file in files:
    job = client.run_external_job(
        algorithm="pulmonary-lobe-segmentation",
        inputs={
            "generic-medical-image": Path(file)
        }
    )
    jobs.append(job)
```

After starting the algorithm jobs, we can inspect their status:

```python
jobs = [client.algorithm_jobs.detail(job.pk) for job in jobs]
print([job.status for job in jobs])
```

After all of your jobs have ended with the status 'Succeeded', you can download the results.

You can also run the Algorithm on an existing Archive on Grand Challenge (if you have been granted access to it).




#### Download inferenced-image results from an algorithm

```python
# loop over the jobs
for job in jobs:
    # Get the input image details
    input_image = client.images.detail(api_url=job.inputs[0])
    input_fn = Path(input_image.file).stem

    for output in job.outputs:
        if output.image is None:
            continue # Not an image
        output_fn = f"{input_fn}_{output.interface.slug}"
        client.images.download(filename=output_fn, files=output_image.files)

```


#### Upload multiple inputs to an algorithm for inference

In this section we will take a look at how to upload multiple inputs to an algorithm on Grand Challenge. As an example we will use Alessa Hering's [Deep Learning-Based Lung Registration](/algorithms/deep-learning-based-ct-lung-registration/) algorithm.

This algorithm requires the following inputs:

- fixed image (CT)
- fixed mask (lungs segmentation)
- moving image (CT)
- moving mask (lungs segmentation)

In this case, all inputs are images. Bear in mind that other input types are possible, see [sockets](/algorithms/interfaces/) for an overview of existing sockets.
We will use the scans from the previous section as well as the algorithm output of the previous algorithm (lung lobes segmentation) in this section.

First, we have to binarize the lobe masks and create lung masks.

```python
# provide paths of the lobe segmentations
lobes = [
    "io/case01_lobes.mha",
    "io/case02_lobes.mha",
]

#loop through the files
for lobe_file in lobes:

    #read image with sitk
    lobe = sitk.ReadImage(lobe_file)
    origin = lobe.GetOrigin()
    spacing = lobe.GetSpacing()
    direction = lobe.GetDirection()
    lobe = sitk.GetArrayFromImage(lobe)

    # binarize
    lobe[lobe >= 1] = 1
    lungs = lobe.astype(np.uint8)
    lungs = sitk.GetImageFromArray(lungs)
    lungs.SetOrigin(origin)
    lungs.SetSpacing(spacing)
    lungs.SetDirection(direction)

    # write the modified image back into file
    sitk.WriteImage(lungs, lobe_file.replace("_lobes", "_lungs"), True)

```

We can retrieve the algorithm, just like we did before:

```python
# retrieve the algorithm
algorithm_2 = client.algorithms.detail(
                  slug="deep-learning-based-ct-lung-registration")

# as a reminder, you can inspect the algorithm object
# to understand what kind of inputs it requires
algorithm_2.interfaces
```

Now we are ready to start a new algorithm job with the required inputs.

```python
# create a job
registration_job = client.run_external_job(
    algorithm="deep-learning-based-ct-lung-registration",
    inputs={
        "fixed-image": Path("io/case01.mha"),
        "moving-image": Path("io/case02.mha"),
        "fixed-mask": Path("io/case01_lungs.mha"),
        "moving-mask": Path("io/case02_lungs.mha"),
    }
)
```

Once the job has been started, we can inspect its status.

```python
registration_job = client.algorithm_jobs.detail(registration_job.pk)
registration_job.status
```

When the job has finished running and ended with the status 'Succeeded', you can download the result(s).

```python
# loop through the outputs, we can simplify things since only images are produced
for output in registration_job.outputs:
    client.images.download(filename=output.interface.slug, url=output.image)
```

⚠️ Note that both these algorithms wrote `.mha` files as outputs. For algorithms that require different outputs, you can loop through the outputs of a successful job and search under "interface", which will tell you what kind of outputs you will have to download.





#### Download the results of an algorithm that produces multiple outputs

In this section we will focus on how to download results from an algorithm that produces multiple outputs. We will use the algorithm for pulmonary lobe segmentation of Covid-19 cases. This algorithm outputs the segmentation for a particular input as well as a "screenshot" of a middle slice for rapid inspection of algorithm performance.

We again start with retrieving the algorithm and inspecting its inputs.

```python
# retrieve the algorithm, providing a slug
algorithm_4 = client.algorithms.detail(
                  slug="pulmonary-lobe-segmentation-for-covid-19-ct-scans")

# explore which inputs the algorithm expects
algorithm_4.interfaces
```

This time, we will use images from an existing archive to pass to the algorithm as inputs.

```python
# save path on your machine
output_archive_dir = 'output_scans'
outputarchivedir_screenshots = 'output_screenshots'

corona_archive = client.archives.detail(slug="coronacasesorg")

# extract image urls
params = {
    'archive': corona_archive.pk,
}
images = client.images.iterate_all(params=params)
urls = [ im.api_url for im in images ]
```

Now we can submit the images from the archive to the algorithm

```python

jobs = []
# submit a job for each file in your file list
for url in urls[:2]:
    job = client.run_external_job(
        algorithm="pulmonary-lobe-segmentation-for-covid-19-ct-scans",
        inputs={
            "ct-image": url
        }
    )
    jobs.append(job)
```

Lets check the status of the job.

```python
jobs = [client.algorithm_jobs.detail(job.pk) for job in jobs]

print([job.status for job in jobs])
```

If the job status is 'Succeeded' we can proceed to downloading the results. In this part we will go through a scenario where we no longer have the details of the particular jobs and inputs.

```python
# get algorithm providing the slug
algorithm_slug = "pulmonary-lobe-segmentation-for-covid-19-ct-scans"
algorithm = client.algorithms.detail(slug=algorithm_slug)

# get the desired archive
archive = client.archives.detail(slug="coronacasesorg")
```

We have generated a set of outputs and a set of inputs. Now, we need to find out which output corresponds to which input. This can be figured out via unique identifiers of the inputs. Each set of inputs has a unique set of ids that can be made into a unique id. Here we create a **mapping between those keys for both the inputs and the outputs**.

```python
# The algorithm image dictates exactly which algorithm image was used
# Using it ensures we only get results from this particular version of the algorithm

algorithm_image_id = "6185b379-e246-4ff3-90cf-2edc76ce0245"
algorithm_image = client.algorithm_images.detail(pk=algorithm_image_id)

# get image api_urls in archive
inputs_to_archive_items = {}

archive_items = client.archive_items.iterate_all(params={"archive": archive.pk})
for archive_item in archive_items:
  key = set(v.pk for value in archive_item.values)
  inputs_to_archive_items[key] = archive_item

# Next we find the job that had parsed these
inputs_to_jobs = {}
jobs = client.algorithm_jobs.iterate_all(params={"algorithm": algorithm.pk})

for job in jobs:
  if job.algorithm_image == algorithm_image.api_url:
      # The version we want

      # Get the key for the inputs
      key = set(v.pk for v in job.inputs)

      if key in inputs:
        inputs_to_jobs[key] = job

# Check if we aren't missing any input that we are expecting!
missing_keys = inputs_to_archive_items.keys() - inputs_to_jobs.keys()
if missing_keys:
    raise ValueError(f"Missing keys in outputs: {missing_keys}")
```

Now, we could loop through the keys and download or manipulate the outputs

```python
for key, archive_item in inputs_to_archive_items.items():
  job = inputs_to_jobs[key]

  for output_value in job.outputs:
    print(output_value)
    # Download, compare, report or do something else with these output values
    ...
```
