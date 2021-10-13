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

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
