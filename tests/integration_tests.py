from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from time import sleep
from uuid import uuid4

import pytest
from httpx import HTTPStatusError

import gcapi
from gcapi import Client
from gcapi.create_strategies import SocketValueSpec
from gcapi.exceptions import MultipleObjectsReturned, ObjectNotFound
from tests.utils import (
    ADMIN_TOKEN,
    ARCHIVE_TOKEN,
    DEMO_PARTICIPANT_TOKEN,
    READERSTUDY_TOKEN,
    recurse_call,
)

TESTDATA = Path(__file__).parent / "testdata"


def test_local_response(local_grand_challenge):
    c = Client(base_url=local_grand_challenge, verify=False, token=ADMIN_TOKEN)
    # Empty response, but it didn't error out so the server is responding
    assert len(c.algorithms.page()) == 0


def test_get_all_reader_study_display_sets(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )
    display_sets = list(
        c.reader_studies.display_sets.iterate_all(
            params={"slug": "reader-study"}
        )
    )
    assert len(display_sets) > 0
    assert isinstance(display_sets[0], gcapi.models.DisplaySet)


def test_get_algorithm_images(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )
    algorithm = c.algorithms.detail(slug="test-algorithm-evaluation-image-0")
    algorithm_images = list(
        c.algorithm_images.iterate_all(params={"algorithm": algorithm.pk})
    )
    assert len(algorithm_images) > 0
    assert isinstance(algorithm_images[0], gcapi.models.AlgorithmImage)


def test_get_answers(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )
    answers = list(
        c.reader_studies.answers.iterate_all(params={"slug": "reader-study"})
    )
    assert len(answers) > 0
    assert all(isinstance(answer, gcapi.models.Answer) for answer in answers)


@pytest.mark.parametrize(
    "token, context",
    [
        (ADMIN_TOKEN, nullcontext()),
        (ARCHIVE_TOKEN, nullcontext()),
        ("whatever", pytest.raises(HTTPStatusError)),
    ],
)
def test_multipart_uploads(token, context, local_grand_challenge):
    client = Client(
        token=token,
        base_url=local_grand_challenge,
        verify=False,
    )
    with open(TESTDATA / "rnddata", "rb") as f:
        with context:
            up = client.uploads.upload_fileobj(fileobj=f, filename="foo")
            assert isinstance(up, gcapi.models.UserUpload)


def test_page_meta_info(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )
    archives = c.archives.page(limit=123)

    assert len(archives) == 1
    assert archives.offset == 0
    assert archives.limit == 123
    assert archives.total_count == 1


def test_download_image(local_grand_challenge, tmpdir):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    display_set = c.reader_studies.display_sets.detail(
        pk="14909328-7a62-4745-8d2a-81a5d936f34b"
    )

    socket_value = display_set.values[3]

    assert socket_value.interface.slug == "generic-medical-image", "Sanity"
    downloaded_files = c.images.download(
        filename=tmpdir / "image",
        url=socket_value.image,
    )

    assert len(downloaded_files) == 1

    # Check that the downloaded file is a mha file
    with downloaded_files[0].open("rb") as fp:
        line = fp.readline().decode("ascii").strip()
    assert line == "ObjectType = Image"


def test_start_algorithm_job(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )

    @recurse_call
    def wait_for_completed_status():
        # algorithm might not be ready yet
        algorithm_image = c.algorithm_images.detail(
            pk="27e09e53-9fe2-4852-9945-32e063393d11"
        )

        if algorithm_image.import_status != "Completed":
            sleep(5)
            raise ValueError("Algorithm image not yet imported")

    wait_for_completed_status()

    job = c.start_algorithm_job(
        algorithm_slug="test-algorithm-evaluation-image-0",
        inputs=[
            SocketValueSpec(
                socket_slug="generic-medical-image",
                file=TESTDATA / "image10x10x101.mha",
            )
        ],
    )

    assert isinstance(job, gcapi.models.JobPost)


def test_get_archive_detail(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=ARCHIVE_TOKEN,
    )

    by_slug = c.archives.detail(slug="archive")
    by_pk = c.archives.detail(pk=by_slug.pk)
    by_api_url = c.archives.detail(by_api_url=by_slug.api_url)

    assert by_pk.pk == by_slug.pk == by_api_url.pk

    assert all(
        [
            isinstance(archive, gcapi.models.Archive)
            for archive in [by_slug, by_pk, by_api_url]
        ]
    )


def test_get_algorithm_detail(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=DEMO_PARTICIPANT_TOKEN,
    )

    by_slug = c.algorithms.detail(slug="test-algorithm-evaluation-image-0")
    by_pk = c.algorithms.detail(pk=by_slug.pk)
    by_api_url = c.algorithms.detail(by_api_url=by_slug.api_url)

    assert by_pk.pk == by_slug.pk == by_api_url.pk

    assert all(
        [
            isinstance(algorithm, gcapi.models.Algorithm)
            for algorithm in [by_slug, by_pk, by_api_url]
        ]
    )


def test_get_reader_study_detail(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=READERSTUDY_TOKEN,
    )

    by_slug = c.reader_studies.detail(slug="reader-study")
    by_pk = c.reader_studies.detail(pk=by_slug.pk)
    by_api_url = c.reader_studies.detail(by_api_url=by_slug.api_url)

    assert by_pk.pk == by_slug.pk == by_api_url.pk

    assert all(
        [
            isinstance(rs, gcapi.models.ReaderStudy)
            for rs in [by_slug, by_pk, by_api_url]
        ]
    )


@pytest.mark.parametrize(
    "keys",
    [
        {"slug": "foo"},
        {"pk": "foo"},
        {"api_url": "foo"},
    ],
)
def test_detail_no_objects(local_grand_challenge, keys):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )
    if "api_url" in keys:
        keys = {
            "api_url": f"{local_grand_challenge}/reader-studies/{keys['api_url']}"
        }

    with pytest.raises(ObjectNotFound):
        c.reader_studies.detail(**keys)


@pytest.mark.parametrize(
    "keys",
    (
        ("api_url", "pk", "slug"),
        ("api_url", "pk"),
        ("api_url", "slug"),
        ("pk", "slug"),
    ),
)
def test_detail_multiple_args(local_grand_challenge, keys):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    with pytest.raises(ValueError):
        c.reader_studies.detail(**{k: "foo" for k in keys})


def test_detail_multiple_objects(local_grand_challenge):
    c = Client(token=ADMIN_TOKEN, base_url=local_grand_challenge, verify=False)

    c.uploads.upload_fileobj(fileobj=BytesIO(b"123"), filename="test")
    c.uploads.upload_fileobj(fileobj=BytesIO(b"456"), filename="test")

    with pytest.raises(MultipleObjectsReturned):
        c.uploads.detail(slug="")


def test_auth_headers_not_sent(local_httpbin):
    c = Client(token="foo")
    response = c.uploads._put_chunk(
        chunk=BytesIO(b"123"), url=f"{local_httpbin}put"
    )
    sent_headers = response.json()["headers"]
    assert not set(c._auth_header.keys()) & set(sent_headers.keys())


def test_update_archive_item(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=ARCHIVE_TOKEN
    )

    # Update the structured value
    updated_display_set = c.update_archive_item(
        archive_item_pk="3dfa7e7d-8895-4f1f-80c2-4172e00e63ea",
        values=[
            SocketValueSpec(
                "generic-medical-image", file=TESTDATA / "image10x10x101.mha"
            )
        ],
    )
    assert isinstance(updated_display_set, gcapi.models.ArchiveItemPost)


def test_update_display_set(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge, verify=False, token=READERSTUDY_TOKEN
    )

    # Update the structured value
    updated_display_set = c.update_display_set(
        display_set_pk="1f8c7dae-9bf8-431b-8b7b-59238985961f",
        values=[
            SocketValueSpec(
                "generic-medical-image", file=TESTDATA / "image10x10x101.mha"
            )
        ],
    )
    assert isinstance(updated_display_set, gcapi.models.DisplaySetPost)


TEST_VALUES = (
    # Image kind
    [
        SocketValueSpec(
            "generic-medical-image",
            file=TESTDATA / "image10x10x101.mha",
        ),
        SocketValueSpec(
            "generic-overlay",
            files=[
                TESTDATA / "image10x10x10.mhd",
                TESTDATA / "image10x10x10.zraw",
            ],
        ),
        SocketValueSpec(
            "a-dicom-image-set-socket",
            files=[
                TESTDATA / "basic.dcm",
            ],
            image_name="foo",
        ),
    ],
    # Value kind
    [
        SocketValueSpec(
            "annotation",
            value={
                "name": "forearm",
                "type": "2D bounding box",
                "corners": [
                    [20, 88, 0.5],
                    [83, 88, 0.5],
                    [83, 175, 0.5],
                    [20, 175, 0.5],
                ],
                "version": {"major": 1, "minor": 0},
            },
        ),
        SocketValueSpec(
            "annotation",
            file=TESTDATA / "annotation.json",
        ),
    ],
    # File kind
    [
        SocketValueSpec(
            "predictions-csv-file",
            file=TESTDATA / "test.csv",
        ),
        SocketValueSpec(
            "predictions-csv-file",
            value="1;2;3\n4;5;6\n",
        ),
    ],
)


@pytest.mark.parametrize("values", TEST_VALUES)
def test_add_case_to_reader_study(values, local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=READERSTUDY_TOKEN,
    )

    ds = c.add_case_to_reader_study(
        reader_study_slug="reader-study",
        values=values,
    )

    assert isinstance(ds, gcapi.models.DisplaySetPost)


@pytest.mark.parametrize("values", TEST_VALUES)
def test_add_case_to_archive(values, local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=ARCHIVE_TOKEN,
    )

    ds = c.add_case_to_archive(
        archive_slug="archive",
        values=values,
    )

    assert isinstance(ds, gcapi.models.ArchiveItemPost)


def test_reuse_existing_images(local_grand_challenge):

    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=READERSTUDY_TOKEN,
    )

    display_set = c.reader_studies.display_sets.detail(
        pk="14909328-7a62-4745-8d2a-81a5d936f34b"
    )

    image_socket_value = None
    for sv in display_set.values:
        if sv.interface.slug == "generic-medical-image":
            image_socket_value = sv
            break
    assert image_socket_value, "Sanity check"

    new_ds = c.add_case_to_reader_study(
        reader_study_slug="reader-study",
        values=[
            SocketValueSpec(
                "generic-medical-image",
                existing_image_api_url=str(image_socket_value.image),
            )
        ],
    )

    assert isinstance(new_ds, gcapi.models.DisplaySetPost)


def test_reuse_existing_socket_values(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=READERSTUDY_TOKEN,
    )

    display_set = c.reader_studies.display_sets.detail(
        pk="14909328-7a62-4745-8d2a-81a5d936f34b"
    )

    # Sanity: double check the source socket value has the expected sockets
    values = display_set.values
    assert len(values) == 4, "Sanity check"

    assert values[0].interface.slug == "a-file-socket"
    assert values[0].interface.super_kind == "File"

    assert values[1].interface.slug == "annotation"
    assert values[1].interface.super_kind == "Value"

    assert values[2].interface.slug == "a-pdf-file-socket"
    assert values[2].interface.super_kind == "File"

    assert values[3].interface.slug == "generic-medical-image"
    assert values[3].interface.super_kind == "Image"

    new_ds = c.add_case_to_reader_study(
        reader_study_slug="reader-study",
        values=[
            SocketValueSpec(
                socket_slug=display_set.values[indx].interface.slug,
                existing_socket_value=display_set.values[indx],
            )
            for indx in range(len(display_set.values))
        ],
    )

    assert isinstance(new_ds, gcapi.models.DisplaySetPost)


def test_add_case_to_reader_study_invalid_socket(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=READERSTUDY_TOKEN,
    )

    with pytest.raises(ValueError) as e:
        c.add_case_to_reader_study(
            reader_study_slug="reader-study",
            values=[
                SocketValueSpec(
                    socket_slug="very-specific-medical-image",
                    file=TESTDATA / "image10x10x10.mha",
                ),
            ],
        )

    assert str(e.value) == (
        "very-specific-medical-image is not an existing socket. "
        "Please provide one from this list: "
        "https://grand-challenge.org/components/interfaces/reader-studies/"
    )


def test_add_cases_to_archive_invalid_socket(local_grand_challenge):
    c = Client(
        base_url=local_grand_challenge,
        verify=False,
        token=ARCHIVE_TOKEN,
    )

    with pytest.raises(ValueError) as e:
        c.add_case_to_archive(
            archive_slug="archive",
            values=[
                SocketValueSpec(
                    socket_slug="very-specific-medical-image",
                    file=TESTDATA / "image10x10x10.mha",
                ),
            ],
        )
    assert str(e.value) == (
        "very-specific-medical-image is not an existing socket. "
        "Please provide one from this list: "
        "https://grand-challenge.org/components/interfaces/inputs/"
    )


def test_title_add_case_to_reader_study(local_grand_challenge):
    title = f"My custom title {uuid4()}"

    with Client(
        base_url=local_grand_challenge,
        verify=False,
        token=READERSTUDY_TOKEN,
    ) as client:
        ds = client.add_case_to_reader_study(
            reader_study_slug="reader-study",
            values=[],
            title=title,
            order=42,
        )

    assert isinstance(ds, gcapi.models.DisplaySetPost)
    assert ds.title == title
    assert ds.order == 42


def test_title_update_display_set(local_grand_challenge):
    updated_title = f"My updated title {uuid4()}"
    updated_order = 10

    with Client(
        base_url=local_grand_challenge,
        verify=False,
        token=READERSTUDY_TOKEN,
    ) as client:
        current_ds = client.reader_studies.display_sets.detail(
            pk="1f8c7dae-9bf8-431b-8b7b-59238985961f"
        )
        assert current_ds.title != updated_title, "Sanity Check"
        assert current_ds.order != updated_order, "Sanity Check"

        ds = client.update_display_set(
            display_set_pk="1f8c7dae-9bf8-431b-8b7b-59238985961f",
            values=[],
            title=updated_title,
            order=updated_order,
        )
        assert isinstance(ds, gcapi.models.DisplaySetPost)
        assert ds.title == updated_title
        assert ds.order == updated_order

        ds = client.update_display_set(
            display_set_pk="1f8c7dae-9bf8-431b-8b7b-59238985961f", values=[]
        )
        assert ds.title == updated_title, "Title should persist if not updated"
        assert ds.order == updated_order, "Order should persist if not updated"

        ds = client.update_display_set(
            display_set_pk="1f8c7dae-9bf8-431b-8b7b-59238985961f",
            values=[],
            title="",
            order=updated_order + 9999,
        )
        assert (
            ds.title == ""
        ), "Can update with empty title to clear title field"


def test_title_add_case_to_archive(local_grand_challenge):
    title = f"My custom title {uuid4()}"

    with Client(
        base_url=local_grand_challenge,
        verify=False,
        token=ARCHIVE_TOKEN,
    ) as client:
        ds = client.add_case_to_archive(
            archive_slug="archive",
            values=[],
            title=title,
        )

        assert isinstance(ds, gcapi.models.ArchiveItemPost)
        assert ds.title == title


def test_title_update_archive_item(local_grand_challenge):
    updated_title = f"My updated title {uuid4()}"

    with Client(
        base_url=local_grand_challenge,
        verify=False,
        token=ARCHIVE_TOKEN,
    ) as client:
        assert (
            client.archive_items.detail(
                pk="3dfa7e7d-8895-4f1f-80c2-4172e00e63ea"
            ).title
            != updated_title
        ), "Sanity Check"
        ds = client.update_archive_item(
            archive_item_pk="3dfa7e7d-8895-4f1f-80c2-4172e00e63ea",
            values=[],
            title=updated_title,
        )

        assert isinstance(ds, gcapi.models.ArchiveItemPost)
        assert ds.title == updated_title

        ai = client.update_archive_item(
            archive_item_pk="3dfa7e7d-8895-4f1f-80c2-4172e00e63ea", values=[]
        )
        assert ai.title == updated_title, "Title should persist if not updated"

        ai = client.update_archive_item(
            archive_item_pk="3dfa7e7d-8895-4f1f-80c2-4172e00e63ea",
            values=[],
            title="",
        )
        assert (
            ai.title == ""
        ), "Can update with empty title to clear title field"
