import base64
import logging
import os
from contextlib import contextmanager
from pathlib import Path

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.db import IntegrityError
from grandchallenge.algorithms.models import Algorithm, AlgorithmImage
from grandchallenge.archives.models import Archive, ArchiveItem
from grandchallenge.cases.models import Image, ImageFile
from grandchallenge.challenges.models import Challenge
from grandchallenge.components.models import (
    ComponentInterface,
    ComponentInterfaceValue,
)
from grandchallenge.core.fixtures import create_uploaded_image
from grandchallenge.evaluation.models import (
    Evaluation,
    Method,
    Phase,
    Submission,
)
from grandchallenge.evaluation.utils import SubmissionKindChoices
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
from knox import crypto
from knox.models import AuthToken
from knox.settings import CONSTANTS

logger = logging.getLogger(__name__)

DEFAULT_USERS = [
    "demo",
    "demop",
    "admin",
    "readerstudy",
    "archive",
]


def run():
    """Creates the main project, demo user and demo challenge."""
    print("🔨 Creating development fixtures 🔨")

    if not settings.DEBUG:
        raise RuntimeError(
            "Skipping this command, server is not in DEBUG mode."
        )

    try:
        users = _create_users(usernames=DEFAULT_USERS)
    except IntegrityError as e:
        raise RuntimeError("Fixtures already initialized") from e

    _set_user_permissions(users)
    _create_demo_challenge(users=users)
    _create_reader_studies(users)
    _create_archive(users)
    _create_user_tokens(users)

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
    _create_algorithm(
        creator=users["demop"],
        inputs=_get_json_file_inputs(),
        outputs=outputs,
        suffix=f"File {challenge_count}",
    )

    print("✨ Test fixtures successfully created ✨")


def _create_users(usernames):
    users = {}

    for username in usernames:
        user = get_user_model().objects.create(
            username=username,
            email=f"{username}@example.com",
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


def _create_demo_challenge(users):
    demo = Challenge.objects.create(
        short_name="demo",
        description="Demo Challenge",
        creator=users["demo"],
        hidden=False,
        display_forum_link=True,
    )
    demo.add_participant(users["demop"])

    phase = Phase.objects.create(challenge=demo, title="Phase 1")

    phase.score_title = "Accuracy ± std"
    phase.score_jsonpath = "acc.mean"
    phase.score_error_jsonpath = "acc.std"
    phase.extra_results_columns = [
        {
            "title": "Dice ± std",
            "path": "dice.mean",
            "error_path": "dice.std",
            "order": "desc",
        }
    ]

    phase.submission_kind = SubmissionKindChoices.ALGORITHM
    phase.save()

    method = Method(phase=phase, creator=users["demo"])

    with _gc_demo_algorithm() as container:
        method.image.save("algorithm_io.tar", container)

    submission = Submission(phase=phase, creator=users["demop"])
    content = ContentFile(base64.b64decode(b""))
    submission.predictions_file.save("test.csv", content)
    submission.save()

    e = Evaluation.objects.create(
        submission=submission, method=method, status=Evaluation.SUCCESS
    )

    def create_result(evaluation, result: dict):
        interface = ComponentInterface.objects.get(slug="metrics-json-file")

        try:
            output_civ = evaluation.outputs.get(interface=interface)
            output_civ.value = result
            output_civ.save()
        except ObjectDoesNotExist:
            output_civ = ComponentInterfaceValue.objects.create(
                interface=interface, value=result
            )
            evaluation.outputs.add(output_civ)

    create_result(
        e,
        {
            "acc": {"mean": 0, "std": 0.1},
            "dice": {"mean": 0.71, "std": 0.05},
        },
    )


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

    question = Question.objects.create(
        reader_study=reader_study,
        question_text="foo",
        answer_type=Question.AnswerType.TEXT,
        widget=QuestionWidgetKindChoices.TEXT_INPUT,
    )

    display_set = DisplaySet.objects.create(
        reader_study=reader_study,
    )
    image = _create_image(
        name="test_image2.mha",
        width=128,
        height=128,
        color_space="RGB",
    )

    annotation_interface = ComponentInterface(
        store_in_database=True,
        relative_path="annotation.json",
        slug="annotation",
        title="Annotation",
        kind=ComponentInterface.Kind.TWO_D_BOUNDING_BOX,
    )
    annotation_interface.save()
    civ = ComponentInterfaceValue.objects.create(
        interface=ComponentInterface.objects.get(slug="generic-medical-image"),
        image=image,
    )
    display_set.values.set([civ])

    answer = Answer.objects.create(
        creator=users["readerstudy"],
        question=question,
        answer="foo",
        display_set=display_set,
    )
    answer.save()


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

    item = ArchiveItem.objects.create(archive=archive)
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
    # Hard code tokens used in gcapi integration tests
    user_tokens = {
        "admin": "1b9436200001f2eaf57cd77db075cbb60a49a00a",
        "readerstudy": "01614a77b1c0b4ecd402be50a8ff96188d5b011d",
        "demop": "00aa710f4dc5621a0cb64b0795fbba02e39d7700",
        "archive": "0d284528953157759d26c469297afcf6fd367f71",
    }

    out = f"{'*' * 80}\n"
    for user, token in user_tokens.items():
        digest = crypto.hash_token(token)

        AuthToken(
            token_key=token[: CONSTANTS.TOKEN_KEY_LENGTH],
            digest=digest,
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


def _get_json_file_inputs():
    return [
        ComponentInterface.objects.get_or_create(
            title="JSON File",
            relative_path="json-file",
            kind=ComponentInterface.Kind.ANY,
            store_in_database=False,
        )[0]
    ]


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
    )

    p = Phase.objects.create(
        challenge=c, title="Phase 1", algorithm_time_limit=300
    )

    p.algorithm_inputs.set(inputs)
    p.algorithm_outputs.set(outputs)

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
    algorithm.inputs.set(inputs)
    algorithm.outputs.set(outputs)
    algorithm.add_editor(creator)

    algorithm_image = AlgorithmImage(creator=creator, algorithm=algorithm)

    with _gc_demo_algorithm() as container:
        algorithm_image.image.save("algorithm_io.tar", container)


@contextmanager
def _gc_demo_algorithm():
    path = Path(__file__).parent / "algorithm_io.tar.gz"
    yield from _uploaded_file(path=path)


@contextmanager
def _uploaded_image_file():
    path = Path(__file__).parent / "image10x10x10.mha"
    yield from _uploaded_file(path=path)


def _uploaded_file(*, path):
    with open(os.path.join(settings.SITE_ROOT, path), "rb") as f:
        with ContentFile(f.read()) as content:
            yield content
