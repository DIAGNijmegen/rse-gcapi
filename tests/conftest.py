import os
import shutil
from collections.abc import Generator
from os import makedirs
from pathlib import Path
from subprocess import STDOUT, check_output
from tempfile import TemporaryDirectory
from time import sleep

import httpx
import pytest
import yaml

from tests.integration_tests import ADMIN_TOKEN


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
    except httpx.HTTPError as e:
        raise e
        local_gc_running = False

    if local_gc_running:
        yield local_api_url
    else:

        # Start our own version of grand challenge
        with TemporaryDirectory() as tmp_path:
            for f in [
                "docker-compose.yml",
                "scripts/minio.py",
            ]:
                get_grand_challenge_file(Path(f), Path(tmp_path))

            for file in (Path(__file__).parent / "scripts").glob("*"):
                if file.is_file():
                    shutil.copy(
                        file,
                        Path(tmp_path) / "scripts" / file.name,
                    )

            docker_gid = int(
                os.environ.get(
                    "DOCKER_GID",
                    check_output(
                        "getent group docker | cut -d: -f3",
                        shell=True,
                        text=True,
                    ),
                ).strip()
            )

            try:
                check_output(
                    [
                        "bash",
                        "-c",
                        f"echo DOCKER_GID={docker_gid} > .env",
                    ],
                    cwd=tmp_path,
                    stderr=STDOUT,
                )
                check_output(
                    ["docker", "compose", "pull"],
                    cwd=tmp_path,
                    stderr=STDOUT,
                )
                check_output(
                    [
                        "docker",
                        "compose",
                        "run",
                        "-v",
                        f"{(Path(tmp_path) / 'scripts').absolute()}:/app/scripts:ro",
                        "--rm",
                        "celery_worker",
                        "bash",
                        "-c",
                        (
                            "python manage.py migrate "
                            "&& python manage.py runscript "
                            "minio create_test_fixtures"
                        ),
                    ],
                    cwd=tmp_path,
                    stderr=STDOUT,
                )
                check_output(
                    [
                        "docker",
                        "compose",
                        "up",
                        "--wait",
                        "--wait-timeout",
                        "300",
                        "-d",
                        "http",
                        "celery_worker",
                    ],
                    cwd=tmp_path,
                    stderr=STDOUT,
                )

                # Give the system some time to import the algorithm image
                sleep(30)

                yield local_api_url

            finally:
                check_output(
                    ["docker", "compose", "down"],
                    cwd=tmp_path,
                    stderr=STDOUT,
                )


def get_grand_challenge_file(repo_path: Path, output_directory: Path) -> None:
    r = httpx.get(
        (
            "https://raw.githubusercontent.com/comic/grand-challenge.org/"
            f"main/{repo_path}"
        ),
        follow_redirects=True,
    )
    r.raise_for_status()

    if str(repo_path) == "docker-compose.yml":
        content = rewrite_docker_compose(r.content)
    else:
        content = r.content

    output_file = output_directory / repo_path
    makedirs(str(output_file.parent), exist_ok=True)

    with open(str(output_file), "wb") as f:
        f.write(content)


def rewrite_docker_compose(content: bytes) -> bytes:
    spec = yaml.safe_load(content)

    for s in spec["services"]:
        # Remove the non-docker socket volume mounts,
        # these are not needed for these tests
        if "volumes" in spec["services"][s]:
            spec["services"][s]["volumes"] = [
                volume
                for volume in spec["services"][s]["volumes"]
                if volume["target"] == "/var/run/docker.sock"
            ]

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

    # Strip watchfiles command from celery
    # as this is not included in the base container
    command = spec["services"]["celery_worker"]["command"]
    command = command.replace('watchfiles --filter python "', "")
    command = command.replace('" /app', "")
    spec["services"]["celery_worker"]["command"] = command

    return yaml.safe_dump(spec).encode("utf-8")
