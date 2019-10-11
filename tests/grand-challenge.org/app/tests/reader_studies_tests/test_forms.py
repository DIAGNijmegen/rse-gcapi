import pytest

from grandchallenge.reader_studies.models import ReaderStudy, Question
from tests.factories import UserFactory, WorkstationFactory
from tests.reader_studies_tests.factories import ReaderStudyFactory
from tests.reader_studies_tests.utils import get_rs_creator, TwoReaderStudies
from tests.utils import get_view_for_user, get_temporary_image


@pytest.mark.django_db
def test_editor_update_form(client):
    rs, _ = ReaderStudyFactory(), ReaderStudyFactory()

    editor = UserFactory()
    rs.editors_group.user_set.add(editor)

    assert rs.editors_group.user_set.count() == 1

    new_editor = UserFactory()
    assert not rs.is_editor(user=new_editor)
    response = get_view_for_user(
        viewname="reader-studies:editors-update",
        client=client,
        method=client.post,
        data={"user": new_editor.pk, "action": "ADD"},
        reverse_kwargs={"slug": rs.slug},
        follow=True,
        user=editor,
    )
    assert response.status_code == 200

    rs.refresh_from_db()
    assert rs.editors_group.user_set.count() == 2
    assert rs.is_editor(user=new_editor)

    response = get_view_for_user(
        viewname="reader-studies:editors-update",
        client=client,
        method=client.post,
        data={"user": new_editor.pk, "action": "REMOVE"},
        reverse_kwargs={"slug": rs.slug},
        follow=True,
        user=editor,
    )
    assert response.status_code == 200

    rs.refresh_from_db()
    assert rs.editors_group.user_set.count() == 1
    assert not rs.is_editor(user=new_editor)


@pytest.mark.django_db
def test_reader_update_form(client):
    rs, _ = ReaderStudyFactory(), ReaderStudyFactory()

    editor = UserFactory()
    rs.editors_group.user_set.add(editor)

    assert rs.readers_group.user_set.count() == 0

    new_reader = UserFactory()
    assert not rs.is_reader(user=new_reader)
    response = get_view_for_user(
        viewname="reader-studies:readers-update",
        client=client,
        method=client.post,
        data={"user": new_reader.pk, "action": "ADD"},
        reverse_kwargs={"slug": rs.slug},
        follow=True,
        user=editor,
    )
    assert response.status_code == 200

    rs.refresh_from_db()
    assert rs.readers_group.user_set.count() == 1
    assert rs.is_reader(user=new_reader)

    response = get_view_for_user(
        viewname="reader-studies:readers-update",
        client=client,
        method=client.post,
        data={"user": new_reader.pk, "action": "REMOVE"},
        reverse_kwargs={"slug": rs.slug},
        follow=True,
        user=editor,
    )
    assert response.status_code == 200

    rs.refresh_from_db()
    assert rs.readers_group.user_set.count() == 0
    assert not rs.is_reader(user=new_reader)


@pytest.mark.django_db
def test_reader_study_create(client):
    # The study creator should automatically get added to the editors group
    creator = get_rs_creator()
    ws = WorkstationFactory()

    def try_create_rs():
        return get_view_for_user(
            viewname="reader-studies:create",
            client=client,
            method=client.post,
            data={
                "title": "foo bar",
                "logo": get_temporary_image(),
                "workstation": ws.pk,
            },
            follow=True,
            user=creator,
        )

    response = try_create_rs()
    assert "error_1_id_workstation" in response.rendered_content

    # The editor must have view permissions for the workstation to add it
    ws.add_user(user=creator)

    response = try_create_rs()
    assert "error_1_id_workstation" not in response.rendered_content
    assert response.status_code == 200

    rs = ReaderStudy.objects.get(title="foo bar")

    assert rs.slug == "foo-bar"
    assert rs.is_editor(user=creator)
    assert not rs.is_reader(user=creator)


@pytest.mark.django_db
def test_question_create(client):
    rs_set = TwoReaderStudies()

    tests = (
        (None, 0, 302),
        (rs_set.editor1, 1, 302),
        (rs_set.reader1, 0, 403),
        (rs_set.editor2, 0, 403),
        (rs_set.reader2, 0, 403),
        (rs_set.u, 0, 403),
    )

    for test in tests:
        response = get_view_for_user(
            viewname="reader-studies:add-question",
            client=client,
            method=client.post,
            data={
                "question_text": "What?",
                "answer_type": "STXT",
                "order": 1,
                "image_port": "",
                "direction": "H",
            },
            reverse_kwargs={"slug": rs_set.rs1.slug},
            user=test[0],
        )
        assert response.status_code == test[2]

        qs = Question.objects.all()

        assert len(qs) == test[1]
        if test[1] > 0:
            question = qs[0]
            assert question.reader_study == rs_set.rs1
            assert question.question_text == "What?"
            question.delete()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "answer_type,port,questions_created",
    (
        ("STXT", "", 1),
        ("STXT", "M", 0),
        ("STXT", "S", 0),
        ("HEAD", "", 1),
        ("HEAD", "M", 0),
        ("HEAD", "S", 0),
        ("BOOL", "", 1),
        ("BOOL", "M", 0),
        ("BOOL", "S", 0),
        ("2DBB", "", 0),
        ("2DBB", "M", 1),
        ("2DBB", "S", 1),
    ),
)
def test_image_port_only_with_bounding_box(
    client, answer_type, port, questions_created
):
    # The image_port should only be set when using a bounding box
    rs_set = TwoReaderStudies()

    assert Question.objects.all().count() == 0

    response = get_view_for_user(
        viewname="reader-studies:add-question",
        client=client,
        method=client.post,
        data={
            "question_text": "What?",
            "answer_type": answer_type,
            "order": 1,
            "image_port": port,
            "direction": "H",
        },
        reverse_kwargs={"slug": rs_set.rs1.slug},
        user=rs_set.editor1,
    )

    assert Question.objects.all().count() == questions_created
