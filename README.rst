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

.. image:: https://readthedocs.org/projects/gcapi/badge/?version=latest
   :target: https://gcapi.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation Status


Python client for the grand-challenge.org API


* Free software: Apache Software License 2.0
* Documentation: https://gcapi.readthedocs.io.


Features
--------

This client library is a handy way to interact with the REST API for grand-challenge.org from python, and provides some convenience methods.

Uploading Files to Archives, Algorithms or Reader Studies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You will need to get an API token, and find the slug of the object you want to upload to.


First, you will need to authorise the client using your personal API token.

.. code:: python

    from gcapi import Client
    
    c = Client(token="Your Personal API Token")

Then, prepare the list of files for each image you want to upload.

.. code:: python

    from pathlib import Path
    
    files = [f.resolve() for f in Path("/path/to/files").iterdir()]

Now, you can upload these files to an Archive, Algorithm or Reader Study which are identified by a slug.
For instance, if you would like to upload to the algorithm at https://grand-challenge.org/algorithms/corads-ai/ you would use ``algorithm="corads-ai"``.
Note that this is case sensitive.

Now you can start the upload.

.. code:: python

    session = c.upload_cases(files=files, algorithm="corads-ai")

You can change ``algorithm`` for ``archive`` or ``reader_study`` there.

You will get a session that starts the conversion of the files, and then adds the standardised images to the selected object once it has succeeded.
You can refresh the session object with

.. code:: python

    session = c(url=session["api_url"])

and check the session status with ``session["status"]``.

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
