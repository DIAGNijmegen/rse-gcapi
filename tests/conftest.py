import os
import shutil
from os import makedirs
from pathlib import Path
from subprocess import CalledProcessError, run
from tempfile import TemporaryDirectory
from time import sleep
from typing import Generator

import httpx
import pytest
import yaml

from tests.integration_tests import ADMIN_TOKEN


@pytest.fixture
def anyio_backend():
    return "asyncio"

def check_call(args, *, cwd=None):
    try:
        run(args, capture_output=True, check=True, cwd=cwd)
    except CalledProcessError as e:
        raise Exception(f"stdout\n\n{e.stdout}\n\nstderr\n\n{e.stderr}")


@pytest.fixture(scope="session")
def local_grand_challenge() -> Generator[str, None, None]:
    local_api_url = "https://gc.localhost/api/v1/"

    try:
        r = httpx.get(
            local_api_url,
            verify=False,
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        r.raise_for_status()
        local_gc_running = True
    except httpx.HTTPError:
        local_gc_running = False

    if local_gc_running:
        yield local_api_url
    else:
        # Start our own version of grand challenge
        with TemporaryDirectory() as tmp_path:
            for f in [
                "docker-compose.yml",
                "dockerfiles/db/postgres.test.conf",
                "Makefile",
                "scripts/development_fixtures.py",
                "scripts/component_interface_value_fixtures.py",
                "scripts/image10x10x10.mha",
                "scripts/minio.py",
                "app/tests/resources/gc_demo_algorithm/copy_io.py",
                "app/tests/resources/gc_demo_algorithm/Dockerfile",
            ]:
                get_grand_challenge_file(Path(f), Path(tmp_path))

            for local_path, container_path in (
                ('/testdata/algorithm_io.tar.gz', 'scripts/algorithm_io.tar.gz'),
                ('/fixtures/algorithm_evaluation_fixtures.py', 'scripts/algorithm_evaluation_fixtures.py'),
            ):
                shutil.copy(
                    os.path.abspath(os.path.dirname(__file__)) + local_path,
                    Path(tmp_path) / container_path,
                )
            try:
                check_call(
                    [
                        "bash",
                        "-c",
                        "echo DOCKER_GID=`getent group docker | cut -d: -f3` > .env",  # noqa: B950
                    ],
                    cwd=tmp_path,
                )
                check_call(
                    ["make", "development_fixtures"],
                    cwd=tmp_path,
                )
                check_call(
                    ["make", "algorithm_evaluation_fixtures"],
                    cwd=tmp_path,
                )
                check_call(
                    [
                        "docker-compose",
                        "up",
                        "-d",
                        "http",
                        "celery_worker",
                        "celery_worker_evaluation",
                    ],
                    cwd=tmp_path,
                )
                check_call(
                    ["docker-compose-wait", "-w", "-t", "5m"],
                    cwd=tmp_path,
                )

                # Give the system some time to import the algorithm image
                sleep(30)

                yield local_api_url

            finally:
                check_call(["docker-compose", "down"], cwd=tmp_path)


def get_grand_challenge_file(repo_path: Path, output_directory: Path) -> None:
    r = httpx.get(
        (
            f"https://raw.githubusercontent.com/comic/grand-challenge.org/"
            f"main/{repo_path}"
        ),
        follow_redirects=True,
    )

    if str(repo_path) == "docker-compose.yml":
        content = rewrite_docker_compose(r.content)
    elif str(repo_path) == "Makefile":
        content = rewrite_makefile(r.content)
    else:
        content = r.content

    output_file = output_directory / repo_path
    makedirs(str(output_file.parent), exist_ok=True)

    with open(str(output_file), "wb") as f:
        f.write(content)


def rewrite_docker_compose(content: bytes) -> bytes:
    spec = yaml.safe_load(content)

    for s in spec["services"]:
        # Remove the non-postgres volume mounts, these are not needed for testing
        if s != "postgres" and "volumes" in spec["services"][s]:
            del spec["services"][s]["volumes"]

        # Replace test with production containers
        if (
            spec["services"][s]["image"]
            == "public.ecr.aws/diag-nijmegen/grand-challenge/web-test:latest"
        ):
            spec["services"][s][
                "image"
            ] = "public.ecr.aws/diag-nijmegen/grand-challenge/web:latest"

    # Use the production web server as the test one is not included
    spec["services"]["web"][
        "command"
    ] = "gunicorn -b 0.0.0.0 -k uvicorn.workers.UvicornWorker config.asgi:application"

    for service in ["celery_worker", "celery_worker_evaluation"]:
        # Strip watchfiles command from celery
        # as this is not included in the base container
        command = spec["services"][service]["command"]
        command = command.replace('watchfiles --filter python "', "")
        command = command.replace('" /app', "")
        spec["services"][service]["command"] = command

    return yaml.safe_dump(spec).encode("utf-8")


def rewrite_makefile(content: bytes) -> bytes:
    # Using `docker compose` with version 2.4.1+azure-1 does not seem to work
    # It works locally with version `2.5.1`, so for now go back to docker-compose
    # If this is fixed docker-compose-wait can be removed and the `--wait`
    # option added to the "up" action above
    makefile = content.decode("utf-8")
    makefile = makefile.replace("docker compose", "docker-compose")
    # Faker is required by development_fixtures.py but not available on the production
    # container. So we add it manually here.
    makefile = makefile.replace(
        "python manage.py migrate && python manage.py runscript minio development_fixtures",
        "python -m pip install faker && python manage.py migrate && python manage.py runscript minio development_fixtures")
    return makefile.encode("utf-8")
