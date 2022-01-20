==========================
Grand Challenge API Client
==========================


.. image:: https://img.shields.io/pypi/v/gcapi.svg
   :target: https://pypi.python.org/pypi/gcapi

.. image:: https://github.com/DIAGNijmegen/rse-gcapi/workflows/CI/badge.svg
   :target: https://github.com/DIAGNijmegen/rse-gcapi/actions?query=workflow%3ACI+branch%3Amaster
   :alt: Build Status

.. image:: https://codecov.io/gh/DIAGNijmegen/rse-gcapi/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/DIAGNijmegen/rse-gcapi
   :alt: Code Coverage Status


Python client for the grand-challenge.org API


* Free software: Apache Software License 2.0


Features
--------

This client library is a handy way to interact with the REST API for grand-challenge.org from python, and provides some
convenience methods.

Authorize with your personal token
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
To authorize on the api you will need your API token. You can generate the token yourself by logging in on
Grand Challenge -> Your Profile -> Manage API Tokens.

Create a token and use it to authorise with the client. Please treat this token like a password!

.. code:: python

    from gcapi import Client

    c = Client(token="Your Personal API Token")


Starting an Algorithm Job
~~~~~~~~~~~~~~~~~~~~~~~~~

First, you need the slug of the algorithm you wish to use. You can get the slug from the url of the algorithm.
For example, if you would like to upload to the algorithm at https://grand-challenge.org/algorithms/corads-ai/ you
would use ``algorithm="corads-ai"``. Note that slugs are case sensitive.

Second, you need to provide the input(s) for the algorithm. The inputs are defined on the algorithm with interfaces,
which are identified by their slugs and determine the type of input that is expected by the algorithm.
There are three super-types of interfaces: ``Image``, ``File`` and ``Value``. For example, for the algorithm at
https://grand-challenge.org/algorithms/corads-ai/ a single input interface with slug ``generic-medical-image`` of
super_kind ``Image`` is defined.

You can get the input interfaces for an algorithm as follows:

.. code:: python

    alg = c.algorithms.detail(slug="corads-ai")

    print(alg["inputs"])
    [{
         'title': 'Generic Medical Image',
         'description': '',
         'slug': 'generic-medical-image',
         'kind': 'Image',
         'pk': 1,
         'default_value': None,
         'super_kind': 'Image'
    }],


You will need to create a dictionary with the keys being the slugs of the interfaces and the values being the values
you want to use. There are two ways to provide a value for an interface of super_kind ``Image``. Either provide a list
of files for an image you want to upload, or provide an image hyperlink if the image is already uploaded to Grand Challenge.

To run an Algorithm with a list of files:

.. code:: python

    from pathlib import Path

    # prepare the files
    files = [f.resolve() for f in Path("/path/to/files").iterdir()]

    # run the algorithm
    job = client.run_external_job(
        algorithm="corads-ai",
        inputs={
            "generic-medical-image": files
        }
    )

To run an Algorithm with an existing image:

.. code:: python

    # run the algorithm
    job = client.run_external_job(
        algorithm="corads-ai",
        inputs={
            "generic-medical-image":
            "https://grand-challenge.org/api/v1/cases/images/.../"
        }
    )

To run an Algorithm with other types of inputs:

.. code:: python

    # run the algorithm
    job = client.run_external_job(
        algorithm="some-algorithm",
        inputs={
            "lung-volume":
            1.234,
            "nodules":
            {...}
        }
    )


The function will run the algorithm with the provided inputs and return a job object.
You can refresh the job object with

.. code:: python

    job = c.algorithm_jobs.detail(job["pk"])

and check the job status with ``job["status"]``.

Uploading Files to Archives or Reader Studies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prepare the list of files for each image you want to upload.

.. code:: python

    from pathlib import Path

    files = [f.resolve() for f in Path("/path/to/files").iterdir()]

Now, you can upload these files to an Archive or Reader Study which are identified by a slug.
For instance, if you would like to upload to the archive at https://grand-challenge.org/archives/radboudcovid/ you
would use ``archive="radboudcovid"``. Note that this is case sensitive.

Now you can start the upload.

.. code:: python

    session = c.upload_cases(files=files, archive="radboudcovid")

You can change ``archive`` to ``reader_study``.

You will get a session that starts the conversion of the files, and then adds the standardised images to the selected
object once it has succeeded.
You can refresh the session object with

.. code:: python

    session = c(url=session["api_url"])

and check the session status with ``session["status"]``.

Downloading Files
-----------------

An image can consist of one or multiple files, such as a single mha file or a dzi and a tiff file. You can download all files
associated with an image at once.

.. code:: python

    from pathlib import Path

    downloaded_files = c.images.download(pk="...", filename=Path("path/to/output"))

You can also use other parameters to identify the image, such as the API URL (use ``url="..."``), and you can also supply the "files" list
directly if you have already obtained the image details.

.. code:: python

    image = c.images.detail(pk="...")
    c.images.download(files=image["files"], filename=Path("path/to/output"))

Note that the filename needs to be specified without file extension. The extension is automatically added because multiple files with
different file extensions can be associated with an image (dzi/tif and mhd/zraw for example).


Retrieve Reader Study Information
---------------------------------

First, you need the slug of the reader study you wish to use. You can get the slug from the url of the reader study.
For example, if you would like to retrieve the information on the reader study at https://grand-challenge.org/reader-studies/reader-study-demo-202/ you
would use ``slug="reader-study-demo-202"``. Note that slugs are case sensitive.

.. code:: python

    rs = next(c.reader_studies.iterate_all(params={"slug": slug}))

You can retrieve only your answers or all answers for that reader study (if you are editor for that reader study) with the following code:

.. code:: python

    my_answers = list(c.reader_studies.answers.mine.iterate_all(params={"question__reader_study": rs["pk"]}))

    answers = list(c.reader_studies.answers.iterate_all(params={"question__reader_study": rs["pk"]}))


If you would like the answers to include readable text for (multiple) choice questions, you can do so
by combining information from the reader study questions.

.. code:: python

    # get the relevant questions in a dictionary with the api_url of the question as the key, and the options for the
    # question as the value. The options contain the readable title.
    choice_questions = {q["api_url"]:q for q in rs["questions"] if q["answer_type"] in ("Choice", "Multiple choice")}

    # local function that will add the readable answer to the answer dictionary for (multiple) choice questions
    def add_answer_title(answer):
        if answer["question"] not in choice_questions:
            return answer
        options = choice_questions[answer["question"]]["options"]
        if isinstance(answer["answer"], list):
            # multiple choice
            answer["readable_answer"] = list(o["title"] for o in options if o["id"] in answer["answer"])
        else:
            # choice
            answer["readable_answer"] = list(o["title"] for o in options if o["id"] == answer["answer"])[0]
        return answer

    # you can create a list for just the (multiple) choice type questions
    choice_answers_readable = list(add_answer_title(a) for a in answers if a["question"] in choice_questions)

    # or add the readable title to all answers
    answers_readable = list(get_readable(a) for a in answers)


If the answers are images, you can download these as follows (see Downloading files):

.. code:: python

    from pathlib import Path

    image_answers = list(a for a in answers if a["answer_image"] is not None)
    for i in image_answers:
        downloaded_files = c.images.download(url=i["answer_image"], filename=Path("path/to/output"))


If you would like to get the answers per case, you can use the following code snippet. A case is defined by the images for that case, you get
get those from the hanging list. Below example uses a simple index as key.

.. code:: python

    import collections

    answers_per_case = {}
    for index, case in enumerate(rs["hanging_list_images"]):
        image_list = list(v for v in case.values())
        answers_per_case[index] = list(
            a
            for a in c_answers
            if collections.Counter(a["images"]) == collections.Counter(image_list)
        )

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
