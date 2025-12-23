# History

## 0.15.1
* Replace thread sensitive async constructs with a thread pool when:
  * Downloading DICOM Image sets
  * Uploading multiple file objects

## 0.15.0
* (Breaking) Removes several deprecated fields from Hyperlinked Image, Question, Reader Study and Display Set
* Uploads of multiple files are now done concurrently using threads
* Adds `title` argument to ArchiveItem and DisplaySet creation and update functions
* Adds `order` to DisplaySet creation and update functions

## 0.14.0
* (Breaking) Add `SocketValueSpec` type of interfaces
* (Breaking) Renaming of helper functions and arguments
* New `download_socket_value` helper function
* New documentation on [github.io](https://diagnijmegen.github.io/rse-gcapi/)
  * Automatically created and uploaded via mkdocs
  * Large number of general documentation improvements
  * New example show how to handle limits cleanly via retry strategy
* Support DICOM image sets, including local de-identification prior to uploading
* `RawImageUploadSession` can now only be viewed and no longer created

## 0.13.4
* Increased typing coverage (making MyPy check more strictly)
* Refactored socket-value creation strategies (related to typing)

## 0.13.3
* Migrate from Poetry to uv
* Remove AsyncClient, only support the synchronous client
* Add algorithm images API
* Update models

## 0.13.3a0 (Alpha-release)
  - Migrate from Poetry to uv

## 0.13.2 (2025-05-27)
- Add missing `packaging` dependency
- Update Grand-Challenge models
- Fix models expecting `json_` fields

## 0.13.1 (2025-05-23)
- Fix incorrectly constructed end-point for version checks

## 0.13.0 (2025-05-21)
  - Version management:
	  - Introduced version checking with reporting on available updates and minimum supported versions (based on Grand Challenge data)
  - Removed Retina endpoints
  - Python version support:
	  - Dropped support for Python 3.8
	  - Added support for Python 3.12 and 3.13
  - Migrated to Pydantic models for request/response validation; all endpoints now return dataclasses
  - Utility function overhaul:
	  - Expanded pre-flight validation and added broader input/Algorithm Interface support
	  - Added: `update_display_set` and `add_cases_to_archive` (analogous to `update_archive_item` and `add_cases_to_reader_study`)
	  - Deprecated: `upload_cases` in favor of the new utility functions
  - Renamed “component-interface” / “interface” to “socket” where applicable
  - Error handling updates:
	  - Disabled retries on HTTP 500 errors
	  - Retries now respect the Retry-After headers in error responses

## 0.12.0 (2023-02-20)

  - Removed support for Python 3.6 and 3.7
  - Added support for Python 3.11

## 0.11.0 (2022-12-14)

  - Added automatic retries with backoff for failed requests
  - Fixed added files to display sets

## 0.10.0 (2022-09-21)

  - Removed client-side json validation, which is instead handled by Grand Challenge
  - Algorithm jobs can be created with inputs that have an interface with superkind file

## 0.9.0 (2022-08-22)

  - Removed `create_display_sets_from_images` utitlity function in favor of `add_cases_to_reader_study`
  - Added support for all interface types in `add_cases_to_reader_study`


## 0.8.0 (2022-07-14)

  - Dropped reader study answer POST data validation
  - Added support for angle answer types

## 0.7.0 (2022-05-02)

  - `page()` now returns a `PageResponse(list)` object rather than a `list`, which adds the attributes `offset`, `limit` and `total_count`
  - Fix uploading files from `str` paths
  - Remove deprecated keys from reader study API
  - Updates `httpx` to `0.22`

## 0.6.3 (2022-03-24)

  - Added support for display items

## 0.6.2 (2022-03-08)

  - Added line answer types to other schemas

## 0.6.1 (2022-03-08)

  - Added line answer types to reader study schema

## 0.6.0 (2022-03-03)

  - **Breaking Change** Removed `_IMAGE` answer types
  - Added support for python 3.9 and 3.10
  - Added line answer types

## 0.5.4 (2022-02-10)

  - Added `archive_item` to `upload_cases` which allows adding images to
    existing archive items
  - Added `interface` to `upload_cases` which allows specifying the
    image type when uploading to archive and archive items. Can only be
    used in combination with `archive` or `archive_item`.
  - Added `update_archive_item` which allows editing of archive item
    values

## 0.5.3 (2021-12-09)

  - Fix redirect from `reader_study.ground_truth`

## 0.5.2 (2021-12-09)

  - Fix `reader_study.ground_truth`

## 0.5.1 (2021-12-02)

  - Added `client.images.download`
  - Removed deprecated `client.raw_image_upload_session_files`

## 0.5.0 (2021-11-01)

  - **Breaking Change** Switched the backend from `requests` to `httpx`
  - **Breaking Change** Removed `client.get_algorithm(algorithm=...)`,
    use `client.algorithms.detail(slug=...)` instead
  - Added `AsyncClient` for asynchronous interation with the Grand
    Challenge API
  - Added option for getting objects by filters in detail view
  - Added optional `timeout` parameter to client
  - Removed deprecated `algorithm` argument to `upload_cases`
  - Added optional `answer` argument to `upload_cases`
  - Added `archives` endpoint
  - Added `MASK` answertype
  - Added optional `follow_redirects`
    argument to `Client.__call__`

## 0.4.0 (2021-06-01)

  - Added `run_external_job` to execute algorithms directly
  - Deprecated the `algorithm` argument to `upload_cases` which will be
    removed in 0.5.0, use `run_external_job` instead

## 0.3.5 (2021-03-01)

  - Allow same domain calls
  - Normalize API tokens

## 0.3.4 (2021-02-03)

  - Fix number answer type support for readerstudy validation

## 0.3.3 (2021-02-02)

  - Adds support for multiple polygon image answers

## 0.3.2 (2021-02-01)

  - Adds support for Number answers

## 0.3.1 (2021-02-01)

  - Adds support for Image answers
  - Allows setting `content` rather than
    `filename` in
    `upload_files`

## 0.3.0 (2020-12-02)

  - Breaking Changes in `upload_cases`:

    - Renamed kwarg `files_to_upload` to `files`
    - `algorithm` kwarg now takes a `slug` rather than a `title`
    - Removed `run_external_algorithm`, use `upload_cases` instead

  - Add Multiple 2D bounding box question types to reader studies

## 0.2.9 (2020-09-29)

  - Add support for ETDRS grid annotation endpoints

## 0.2.8 (2020-06-05)

  - Skip validation of PATCH requests

## 0.2.7 (2020-05-16)

  - Fixed reader study detail lookups

## 0.2.6 (2020-05-15)

  - Note: this release has been yanked from pypi
  - Added support for retina polygon annotation sets and retina single
    polygon annotations
  - If authentication token is unset, the
    `GRAND_CHALLENGE_AUTHORIZATION` will
    be used as a fallback

## 0.2.5 (2020-04-24)

  - Allow null answers

## 0.2.4 (2020-04-03)

  - Added GET request params

## 0.2.3 (2020-03-26)

  - Added ground truth endpoint for reader studies

## 0.2.2 (2020-03-24)

  - Added support for uploading to archives and reader studies

## 0.2.1 (2020-03-23)

  - Added Polygon and Choice question types to reader studies

## 0.2.0 (2020-02-09)

  - Dropped Python 2.7 and 3.5
  - Added support for Python 3.7 and 3.8

## 0.1.0 (2019-05-07)

  - First release on PyPI.
