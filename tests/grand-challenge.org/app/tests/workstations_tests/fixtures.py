from typing import NamedTuple

import pytest
from django.contrib.auth.models import User

from grandchallenge.workstations.models import Workstation, WorkstationImage
from tests.factories import (
    WorkstationFactory,
    WorkstationImageFactory,
    UserFactory,
)


class WorkstationSet(NamedTuple):
    workstation: Workstation
    editor: User
    user: User
    user1: User
    image: WorkstationImage


class TwoWorkstationSets(NamedTuple):
    ws1: WorkstationSet
    ws2: WorkstationSet


def workstation_set():
    ws = WorkstationFactory()
    wsi = WorkstationImageFactory(workstation=ws)
    e, u, u1 = UserFactory(), UserFactory(), UserFactory()
    wss = WorkstationSet(workstation=ws, editor=e, user=u, user1=u1, image=wsi)
    wss.workstation.add_editor(user=e)
    wss.workstation.add_user(user=u)
    return wss


@pytest.fixture
def two_workstation_sets() -> TwoWorkstationSets:
    return TwoWorkstationSets(ws1=workstation_set(), ws2=workstation_set())
