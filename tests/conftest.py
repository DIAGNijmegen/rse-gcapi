import os
import re
import shutil
import subprocess
import tarfile
from collections.abc import Generator
from os import makedirs
from pathlib import Path
from subprocess import STDOUT, check_output
from time import sleep
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from tests.integration_tests import ADMIN_TOKEN


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def local_httpbin():
    container_id = None
    try:
        container_id = check_output(
            ["docker", "run", "-d", "-p", "8008:80", "kennethreitz/httpbin"],
            text=True,
        ).strip()

        url = "http://localhost:8008/"
        for _ in range(5):
            try:
                response = httpx.get(url, timeout=5)
                response.raise_for_status()
                break
            except (httpx.RequestError, httpx.HTTPStatusError):
                sleep(1)
        else:
            raise RuntimeError(f"Failed to connect to {url}")

        yield url

    finally:
        if container_id:
            # Stop and remove the container
            check_output(
                ["docker", "stop", container_id],
                stderr=STDOUT,
            )
            check_output(
                ["docker", "rm", container_id],
                stderr=STDOUT,
            )


class GrandChallengeServerRuntimeError(RuntimeError):
    pass


@pytest.fixture(scope="session")
def local_grand_challenge(tmp_path_factory) -> Generator[str, None, None]:

    local_api_url = os.environ.get(
        "GCAPI_TESTS_LOCAL_API_URL",
        "https://gc.localhost:8000/api/v1/",
    )

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
        tmp_name = tmp_path_factory.mktemp("grand_challenge_repo")
        tmp_path = Path(tmp_name)

        # Clone the repo
        check_output(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "git@github.com:comic/grand-challenge.org.git",
                tmp_path,
            ],
            stderr=STDOUT,
        )

        virtual_env_path = tmp_path_factory.mktemp("grand_challenge_venv")
        check_output(
            ["uv", "venv", str(virtual_env_path)],
            cwd=tmp_path,
            stderr=STDOUT,
        )

        # Copy our test scripts
        for file in (Path(__file__).parent / "scripts").glob("*"):
            if file.is_file():
                shutil.copy(
                    file,
                    tmp_path / "scripts" / file.name,
                )

        shim_location_path = tmp_path_factory.mktemp("grand_challenge_shim")
        shim_version = download_latest_sagemaker_shim(shim_location_path)

        env = build_env(
            shim_location=shim_location_path,
            shim_version=shim_version,
            virtual_env_path=virtual_env_path,
        )

        key_path, crt_path = build_ssl_certs(tmp_path)
        check_output(  # Required for Django to serve HTTPS
            ["uv", "pip", "install", "pyopenssl"],
            cwd=tmp_path,
            stderr=STDOUT,
            env=env,
        )

        background_processes = []

        try:
            # Run dependencies
            deps_process = subprocess.Popen(
                ["make", "rundeps"],
                env=env,
                cwd=tmp_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            background_processes.append(deps_process)

            # Migrate
            check_output(
                [
                    "uv",
                    "run",
                    "--active",
                    "--directory",
                    "app",
                    "python",
                    "manage.py",
                    "migrate",
                ],
                env=env,
                cwd=tmp_path,
                stderr=STDOUT,
            )

            # Start the celery worker
            celery_worker_process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "--active",
                    "--directory",
                    "app",
                    "celery",
                    "--app",
                    "config",
                    "worker",
                    "--concurrency",
                    "1",
                    "--pool",
                    "prefork",
                    "--queues",
                    "workstations-eu-central-1,acks-late-2xlarge,acks-late-2xlarge-delay,acks-late-micro-short,acks-late-micro-short-delay",
                ],
                env=env,
                cwd=tmp_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            background_processes.append(celery_worker_process)

            check_output(
                [
                    "uv",
                    "run",
                    "--active",
                    "--directory",
                    "app",
                    "python",
                    "manage.py",
                    "runscript",
                    "--pythonpath=../",
                    "minio",
                    "create_test_fixtures",
                ],
                env=env,
                cwd=tmp_path,
                stderr=STDOUT,
            )

            server_process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "--active",
                    "--directory",
                    "app",
                    "python",
                    "manage.py",
                    "runserver_plus",
                    "--cert-file",
                    str(crt_path.absolute()),
                    "--key-file",
                    str(key_path.absolute()),
                ],
                env=env,
                cwd=tmp_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            background_processes.append(server_process)

            sleep(5)  # Give processes a short while to properly start/fail

            # Check for early errors
            _check_for_server_errors(background_processes)

            yield local_api_url

        except GrandChallengeServerRuntimeError:
            # Reraise server runtime errors as is
            raise
        except Exception as e:
            # If setup fails, check if any background server processes had errors
            _check_for_server_errors(background_processes, cause=e)
            raise
        finally:
            # Always cleanup
            check_output(
                [
                    "docker",
                    "compose",
                    "down",
                    "--volumes",
                    "--remove-orphans",
                ],
                cwd=tmp_path,
                stderr=STDOUT,
            )
            for process in background_processes:
                process.terminate()
                try:
                    # Join with a timeout so we don't hang forever
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()


def _check_for_server_errors(processes, cause=None):
    """Check background processes for errors and report them."""
    errors = []

    for process in processes:
        # First check if process already exited with error
        if process.poll() is not None and process.returncode != 0:
            stdout, stderr = process.communicate(timeout=1)
            errors.append(
                {
                    "cmd": str(process.args),
                    "returncode": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            )

    if errors:
        # Format error message with all process outputs
        error_msg = "\n\n=== Background Process Errors ===\n"
        for err in errors:
            error_msg += f"\nProcess: {err['cmd']}\n"
            error_msg += f"Return code: {err['returncode']}\n"
            if err["stdout"]:
                error_msg += f"STDOUT:\n{err['stdout']}\n"
            if err["stderr"]:
                error_msg += f"STDERR:\n{err['stderr']}\n"
            error_msg += "-" * 50 + "\n"

        # Raise with chained exception if there was a cause
        if cause:
            raise GrandChallengeServerRuntimeError(error_msg) from cause
        else:
            pytest.fail(error_msg, pytrace=False)


def download_latest_sagemaker_shim(download_path: Path) -> str:
    """Download the latest sagemaker shim release from GitHub and extract it."""

    api_url = "https://api.github.com/repos/DIAGNijmegen/rse-sagemaker-shim/releases/latest"
    resp = httpx.get(api_url, timeout=10)
    resp.raise_for_status()
    release = resp.json()

    match = None
    for asset in release.get("assets", []):
        name = asset["name"]
        if match := re.match(
            r"sagemaker-shim-(.*)-Linux-x86_64\.tar\.gz", name
        ):
            url = asset["browser_download_url"]
            print(f"Downloading {name} from {url}...")
            with httpx.stream("GET", url=url, follow_redirects=True) as r:
                r.raise_for_status()
                with open(download_path / name, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)

            # Extract the downloaded tar.gz file
            tar_path = download_path / name
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=download_path, filter="fully_trusted")

            # Remove the tar.gz file after extraction
            tar_path.unlink()
            break

    if match is None:
        raise RuntimeError("Could not find suitable sagemaker shim release.")
    else:
        return str(match.group(1))  # Return the version string


def build_env(
    shim_location: Path, shim_version: str, virtual_env_path: Path
) -> dict[str, Any]:
    env = os.environ.copy()

    env["VIRTUAL_ENV"] = str(virtual_env_path.absolute())
    env_vars = {
        # DOCKER_GID is only used for resolving the docker-compose.yml template
        # Actual service it is involved with does not matter for these tests
        "DOCKER_GID": "999",
        "POSTGRES_HOST": "localhost",
        "SITE_SERVER_PORT": "8000",
        "DEFAULT_SCHEME": "https",
        "SECURE_SSL_REDIRECT": "False",
        "CSRF_COOKIE_SECURE": "False",
        "SESSION_COOKIE_SECURE": "False",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",
        "AWS_S3_ENDPOINT_URL": "http://localhost:9000",
        "COMPONENTS_S3_ENDPOINT_URL": "http://minio.localhost:9000",
        "PROTECTED_S3_CUSTOM_DOMAIN": "gc.localhost:8000/media",
        "AWS_S3_URL_PROTOCOL": "https:",
        "COMPONENTS_REGISTRY_INSECURE": "True",
        "COMPONENTS_DEFAULT_BACKEND": "tests.components_tests.resources.backends.IOCopyExecutor",
        "COMPONENTS_SAGEMAKER_SHIM_LOCATION": str(shim_location.absolute()),
        "COMPONENTS_VIRTUAL_ENV_BIOM_LOCATION": "PLEASE FIX ME EVENTUALLY",
        "COMPONENTS_SAGEMAKER_SHIM_VERSION": shim_version,
        "COMPONENTS_REGISTRY_URL": "localhost:5000",
        "COMPONENTS_DOCKER_KEEP_CAPS_UNSAFE": "True",
        "DEBUG": "True",
        "COMPRESS_OFFLINE": "False",
        "STATIC_ROOT": "../.static/",
        "REDIS_ENDPOINT": "redis://localhost:6379",
        "USING_MINIO": "True",
    }

    env.update(env_vars)

    return env


def build_ssl_certs(base_path: Path) -> tuple[Path, Path]:
    """
    Build self-signed SSL certificates for local testing.

    Returns paths to the key and certificate files.
    """
    certs_path = base_path / "certs"
    makedirs(certs_path, exist_ok=True)

    key_path = certs_path / "dev.key"
    crt_path = certs_path / "dev.crt"

    check_output(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:4096",
            "-keyout",
            str(key_path.absolute()),
            "-out",
            str(crt_path.absolute()),
            "-days",
            "365",
            "-nodes",
            "-subj",
            "/CN=gc.localhost",
        ],
        stderr=STDOUT,
    )

    return key_path, crt_path


@pytest.fixture(autouse=True)
def mock_check_version():
    with patch("gcapi.client.check_version") as mock:
        yield mock
