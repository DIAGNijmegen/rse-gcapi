=======
History
=======

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
