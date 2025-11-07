import gzip
import logging
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.test import override_settings
from django.utils.timezone import now
from grandchallenge.algorithms.models import (
    Algorithm,
    AlgorithmImage,
    AlgorithmInterface,
)
from grandchallenge.archives.models import Archive, ArchiveItem
from grandchallenge.cases.models import Image, ImageFile
from grandchallenge.challenges.models import Challenge
from grandchallenge.components.backends import docker_client
from grandchallenge.components.models import (
    ComponentInterface,
    ComponentInterfaceValue,
)
from grandchallenge.core.fixtures import create_uploaded_image
from grandchallenge.evaluation.models import Method, Phase
from grandchallenge.evaluation.utils import SubmissionKindChoices
from grandchallenge.hanging_protocols.models import HangingProtocol
from grandchallenge.invoices.models import Invoice
from grandchallenge.reader_studies.models import (
    Answer,
    DisplaySet,
    Question,
    QuestionWidgetKindChoices,
    ReaderStudy,
)
from grandchallenge.verifications.models import Verification
from grandchallenge.workstations.models import Workstation
from knox.models import AuthToken, hash_token
from knox.settings import CONSTANTS

from .constants import USER_TOKENS

logger = logging.getLogger(__name__)

DEFAULT_USERS = [
    "demo",
    "demop",
    "admin",
    "readerstudy",
    "archive",
]


@override_settings(task_eager_propagates=True, task_always_eager=True)
def run():
    """Creates the main project, demo user and demo challenge."""
    print("🔨 Creating test fixtures 🔨")

    if not settings.DEBUG:
        raise RuntimeError(
            "Skipping this command, server is not in DEBUG mode."
        )

    try:
        users = _create_users(usernames=DEFAULT_USERS)
    except IntegrityError as e:
        raise RuntimeError("Fixtures already initialized") from e

    _set_user_permissions(users)
    _create_reader_studies(users)
    _create_archive(users)
    _create_user_tokens(users)

    _create_extra_sockets()

    inputs = _get_inputs()
    outputs = _get_outputs()
    challenge_count = Challenge.objects.count()
    archive = _create_phase_archive(
        creator=users["demo"], interfaces=inputs, suffix=challenge_count
    )
    _create_challenge(
        creator=users["demo"],
        participant=users["demop"],
        archive=archive,
        suffix=challenge_count,
        inputs=inputs,
        outputs=outputs,
    )
    _create_algorithm(
        creator=users["demop"],
        inputs=inputs,
        outputs=outputs,
        suffix=f"Image {challenge_count}",
    )

    print("✨ Test fixtures successfully created ✨")


def _create_users(usernames):
    users = {}

    for username in usernames:
        user = get_user_model().objects.create(
            username=username,
            email=f"{username}@example.test",
            is_active=True,
            first_name=username,
            last_name=username,
        )
        user.set_password(username)
        user.save()

        EmailAddress.objects.create(
            user=user,
            email=user.email,
            verified=True,
            primary=True,
        )

        Verification.objects.create(
            user=user,
            email=user.email,
            is_verified=True,
        )

        user.user_profile.institution = f"University of {username}"
        user.user_profile.department = f"Department of {username}s"
        user.user_profile.country = "NL"
        user.user_profile.receive_newsletter = True
        user.user_profile.save()
        users[username] = user

    return users


def _set_user_permissions(users):
    users["admin"].is_staff = True
    users["admin"].save()

    rs_group = Group.objects.get(
        name=settings.READER_STUDY_CREATORS_GROUP_NAME
    )
    users["readerstudy"].groups.add(rs_group)

    add_archive_perm = Permission.objects.get(codename="add_archive")
    users["archive"].user_permissions.add(add_archive_perm)
    users["demo"].user_permissions.add(add_archive_perm)


def _create_reader_studies(users):
    reader_study = ReaderStudy.objects.create(
        title="Reader Study",
        workstation=Workstation.objects.get(
            slug=settings.DEFAULT_WORKSTATION_SLUG
        ),
        logo=create_uploaded_image(),
        description="Test reader study",
        view_content={"main": ["generic-medical-image"]},
    )
    reader_study.editors_group.user_set.add(users["readerstudy"])
    reader_study.readers_group.user_set.add(users["demo"])

    hanging_protocol = HangingProtocol.objects.create(
        title="test",
        creator=users["readerstudy"],
        json=[{"viewport_name": "main"}],
    )

    reader_study.hanging_protocol = hanging_protocol
    reader_study.save()

    question = Question.objects.create(
        reader_study=reader_study,
        question_text="foo",
        answer_type=Question.AnswerType.TEXT,
        widget=QuestionWidgetKindChoices.TEXT_INPUT,
    )

    display_set = DisplaySet.objects.create(
        pk="14909328-7a62-4745-8d2a-81a5d936f34b",
        reader_study=reader_study,
    )
    image = _create_image(
        name="test_image2.mha",
        width=128,
        height=128,
        color_space="RGB",
    )
    image_civ = ComponentInterfaceValue.objects.create(
        interface=ComponentInterface.objects.get(slug="generic-medical-image"),
        image=image,
    )

    # Create two type of files: one JSON, one csv
    json_file_interface = ComponentInterface(
        store_in_database=False,
        relative_path="file.json",
        slug="file-socket",
        title="A file socket",
        kind=ComponentInterface.Kind.ANY,
    )
    json_file_interface.save()

    json_file_civ = ComponentInterfaceValue.objects.create(
        interface=json_file_interface,
    )
    with ContentFile(b"42") as content:
        json_file_civ.file.save("file.json", content)
        json_file_civ.save()

    pdf_file_interface = ComponentInterface(
        store_in_database=False,
        relative_path="file.pdf",
        slug="pdf-file-socket",
        title="A pdf file socket",
        kind=ComponentInterface.Kind.PDF,
    )
    pdf_file_interface.save()

    pdf_file_civ = ComponentInterfaceValue.objects.create(
        interface=pdf_file_interface,
    )
    with ContentFile(b"42") as content:
        pdf_file_civ.file.save("file.pdf", content)
        pdf_file_civ.save()

    annotation_interface = ComponentInterface(
        store_in_database=True,
        relative_path="annotation.json",
        slug="annotation",
        title="Annotation",
        kind=ComponentInterface.Kind.TWO_D_BOUNDING_BOX,
    )
    annotation_interface.save()
    value_civ = ComponentInterfaceValue.objects.create(
        interface=annotation_interface,
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
    )

    # Note: ordering is based on the slug here
    display_set.values.set([image_civ, json_file_civ, pdf_file_civ, value_civ])

    display_set_with_answer = DisplaySet.objects.create(
        reader_study=reader_study,
    )
    answer = Answer.objects.create(
        creator=users["readerstudy"],
        question=question,
        answer="foo",
        display_set=display_set_with_answer,
    )
    answer.save()

    DisplaySet.objects.create(  # Display set that can be directly updated
        pk="1f8c7dae-9bf8-431b-8b7b-59238985961f",
        reader_study=reader_study,
    )


def _create_archive(users):
    archive = Archive.objects.create(
        title="Archive",
        workstation=Workstation.objects.get(
            slug=settings.DEFAULT_WORKSTATION_SLUG
        ),
        logo=create_uploaded_image(),
        description="Test archive",
    )
    archive.editors_group.user_set.add(users["archive"])
    archive.uploaders_group.user_set.add(users["demo"])

    item = ArchiveItem.objects.create(
        pk="3dfa7e7d-8895-4f1f-80c2-4172e00e63ea",
        archive=archive,
    )
    civ = ComponentInterfaceValue.objects.create(
        interface=ComponentInterface.objects.get(slug="generic-medical-image"),
        image=_create_image(
            name="test_image2.mha",
            width=128,
            height=128,
            color_space="RGB",
        ),
    )

    item.values.add(civ)


def _create_user_tokens(users):
    out = f"{'*' * 80}\n"
    for user, token in USER_TOKENS.items():
        AuthToken(
            token_key=token[: CONSTANTS.TOKEN_KEY_LENGTH],
            key=hash_token(token),
            user=users[user],
            expiry=None,
        ).save()

        out += f"\t{user} token is: {token}\n"
    out += f"{'*' * 80}\n"
    logger.debug(out)


image_counter = 0


def _create_image(**kwargs):
    global image_counter

    im = Image.objects.create(**kwargs)
    im_file = ImageFile.objects.create(image=im)

    with _uploaded_image_file() as f:
        im_file.file.save(f"test_image_{image_counter}.mha", f)
        image_counter += 1
        im_file.save()

    return im


def _get_inputs():
    return ComponentInterface.objects.filter(
        slug__in=["generic-medical-image"]
    )


def _get_outputs():
    return ComponentInterface.objects.filter(
        slug__in=["generic-medical-image", "results-json-file"]
    )


def _create_phase_archive(*, creator, interfaces, suffix, items=5):
    a = Archive.objects.create(
        title=f"Algorithm Evaluation {suffix} Test Set",
        logo=create_uploaded_image(),
        workstation=Workstation.objects.get(
            slug=settings.DEFAULT_WORKSTATION_SLUG
        ),
    )
    a.add_editor(creator)

    for n in range(items):
        ai = ArchiveItem.objects.create(archive=a)
        for interface in interfaces:
            v = ComponentInterfaceValue.objects.create(interface=interface)

            im = Image.objects.create(
                name=f"Test Image {n}", width=10, height=10
            )
            im_file = ImageFile.objects.create(image=im)

            with _uploaded_image_file() as f:
                im_file.file.save(f"test_image_{n}.mha", f)
                im_file.save()

            v.image = im
            v.save()

            ai.values.add(v)

    return a


def _create_challenge(
    *, creator, participant, archive, suffix, inputs, outputs
):
    c = Challenge.objects.create(
        short_name=f"algorithm-evaluation-{suffix}",
        creator=creator,
        hidden=False,
        logo=create_uploaded_image(),
    )
    c.add_participant(participant)

    Invoice.objects.create(
        challenge=c,
        support_costs_euros=0,
        compute_costs_euros=10,
        storage_costs_euros=0,
        payment_status=Invoice.PaymentStatusChoices.PAID,
        billing_address="Geert Grooteplein Zuid 10, 6525 GA Nijmegen",
        contact_email="invoices@example.org",
        contact_name="Jane Doe",
        paid_on=now(),
        vat_number="NL12345678",
    )

    p = Phase.objects.create(
        challenge=c, title="Phase 1", algorithm_time_limit=300
    )

    interface = AlgorithmInterface.objects.create(
        inputs=inputs, outputs=outputs
    )
    p.algorithm_interfaces.set([interface])

    p.title = "Algorithm Evaluation"
    p.submission_kind = SubmissionKindChoices.ALGORITHM
    p.archive = archive
    p.score_jsonpath = "score"
    p.submissions_limit_per_user_per_period = 10
    p.save()

    m = Method(creator=creator, phase=p)

    with _gc_demo_algorithm() as container:
        m.image.save("algorithm_io.tar", container)


def _create_algorithm(*, creator, inputs, outputs, suffix):
    algorithm = Algorithm.objects.create(
        title=f"Test Algorithm Evaluation {suffix}",
        logo=create_uploaded_image(),
    )

    interface = AlgorithmInterface.objects.create(
        inputs=inputs, outputs=outputs
    )
    algorithm.interfaces.set([interface])

    algorithm.add_editor(creator)

    algorithm_image = AlgorithmImage(
        pk="27e09e53-9fe2-4852-9945-32e063393d11",
        creator=creator,
        algorithm=algorithm,
    )

    with _gc_demo_algorithm() as container:
        algorithm_image.image.save("algorithm_io.tar", container)


def _create_extra_sockets():
    ComponentInterface.objects.create(
        store_in_database=False,
        relative_path="images/dicom-image-set",
        slug="dicom-image-set",
        title="A DICOM image set socket",
        kind=ComponentInterface.Kind.DICOM_IMAGE_SET,
    )


@contextmanager
def _gc_demo_algorithm():
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        repo_tag = "fixtures-algorithm-io:latest"

        docker_client.build_image(
            path=str(Path(__file__).parent.absolute()), repo_tag=repo_tag
        )

        outfile = tmp_path / f"{repo_tag}.tar"
        output_gz = f"{outfile}.gz"

        docker_client.save_image(repo_tag=repo_tag, output=outfile)

        with open(outfile, "rb") as f_in:
            with gzip.open(output_gz, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        yield from _uploaded_file(path=output_gz)


@contextmanager
def _uploaded_image_file():
    path = Path(__file__).parent / "image10x10x10.mha"
    yield from _uploaded_file(path=path)


def _uploaded_file(*, path):
    with open(os.path.join(settings.SITE_ROOT, path), "rb") as f:
        with ContentFile(f.read()) as content:
            yield content
