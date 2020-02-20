from os import makedirs
from pathlib import Path
from subprocess import check_call
from tempfile import TemporaryDirectory
from typing import Generator

import pytest
import requests
import yaml

from tests.integration_tests import ADMIN_TOKEN


@pytest.yield_fixture(scope="session")
def local_grand_challenge() -> Generator[str, None, None]:
    local_api_url = "https://gc.localhost/api/v1/"

    try:
        r = requests.get(
            local_api_url,
            verify=False,
            headers={"Authorization": f"TOKEN {ADMIN_TOKEN}"},
        )
        r.raise_for_status()
        local_gc_running = True
    except requests.exceptions.ConnectionError:
        local_gc_running = False

    if local_gc_running:
        yield local_api_url
    else:
        # Start our own version of grand challenge
        with TemporaryDirectory() as tmp_path:

            for f in [
                "docker-compose.yml",
                "dockerfiles/db/postgres.test.conf",
            ]:
                get_grand_challenge_file(Path(f), Path(tmp_path))

            try:
                check_call(["docker-compose", "pull"], cwd=tmp_path)

                for command in [
                    "migrate",
                    "check_permissions",
                    "init_gc_demo",
                ]:
                    check_call(
                        [
                            "docker-compose",
                            "run",
                            "--rm",
                            "web",
                            "python",
                            "manage.py",
                            command,
                        ],
                        cwd=tmp_path,
                    )
                check_call(["docker-compose", "up", "-d"], cwd=tmp_path)
                check_call(
                    ["docker-compose-wait", "-w", "-t", "2m"], cwd=tmp_path
                )

                yield local_api_url

            finally:
                check_call(["docker-compose", "down"], cwd=tmp_path)


def get_grand_challenge_file(repo_path: Path, output_directory: Path) -> None:
    r = requests.get(
        (
            f"https://raw.githubusercontent.com/comic/grand-challenge.org/"
            f"master/{repo_path}"
        ),
        allow_redirects=True,
    )

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
        # Remove the non-postgres volume mounts, these are not needed for testing
        if s != "postgres" and "volumes" in spec["services"][s]:
            del spec["services"][s]["volumes"]

        # Replace test with production containers
        if spec["services"][s]["image"] == "grandchallenge/web-test:latest":
            spec["services"][s]["image"] = "grandchallenge/web:latest"

    # Use the production web server as the test one is not included
    spec["services"]["web"][
        "command"
    ] = "gunicorn -b 0.0.0.0 -k uvicorn.workers.UvicornWorker config.asgi:application"

    return yaml.safe_dump(spec).encode("utf-8")
