=======
History
=======

0.5.0 (UNRELEASED)
------------------

* **Breaking Change** Switched the backend from ``requests`` to ``httpx``
* **Breaking Change** Removed ``client.get_algorithm(algorithm=...)``, use ``client.algorithms.detail(slug=...)`` instead
* Added option for getting objects by filters in detail view
* Add optional ``timeout`` parameter to client
* Removed deprecated ``algorithm`` argument to ``upload_cases``
* Added ``archives`` endpoint
* Added ``MASK`` answertype

0.4.0 (2021-06-01)
------------------

* Added ``run_external_job`` to execute algorithms directly
* Deprecated the ``algorithm`` argument to ``upload_cases`` which will be removed in 0.5.0, use ``run_external_job`` instead

0.3.5 (2021-03-01)
------------------

* Allow same domain calls
* Normalize API tokens

0.3.4 (2021-02-03)
------------------

* Fix number answer type support for readerstudy validation

0.3.3 (2021-02-02)
------------------

* Adds support for multiple polygon image answers

0.3.2 (2021-02-01)
------------------

* Adds support for Number answers

0.3.1 (2021-02-01)
------------------

* Adds support for Image answers
* Allows setting `content` rather than `filename` in `upload_files`

0.3.0 (2020-12-02)
------------------

* Breaking Changes in ``upload_cases``:
    * Renamed kwarg ``files_to_upload`` to ``files``
    * ``algorithm`` kwarg now takes a ``slug`` rather than a ``title``
    * Removed ``run_external_algorithm``, use ``upload_cases`` instead
* Add Multiple 2D bounding box question types to reader studies

0.2.9 (2020-09-29)
------------------

* Add support for ETDRS grid annotation endpoints

0.2.8 (2020-06-05)
------------------

* Skip validation of PATCH requests

0.2.7 (2020-05-16)
------------------

* Fixed reader study detail lookups

0.2.6 (2020-05-15)
------------------

* Note: this release has been yanked from pypi
* Added support for retina polygon annotation sets and retina single polygon annotations
* If authentication token is unset, the `GRAND_CHALLENGE_AUTHORIZATION` will be used as a fallback

0.2.5 (2020-04-24)
------------------

* Allow null answers

0.2.4 (2020-04-03)
------------------

* Added GET request params

0.2.3 (2020-03-26)
------------------

* Added ground truth endpoint for reader studies

0.2.2 (2020-03-24)
------------------

* Added support for uploading to archives and reader studies

0.2.1 (2020-03-23)
------------------

* Added Polygon and Choice question types to reader studies

0.2.0 (2020-02-09)
------------------

* Dropped Python 2.7 and 3.5
* Added support for Python 3.7 and 3.8

0.1.0 (2019-05-07)
------------------

* First release on PyPI.
