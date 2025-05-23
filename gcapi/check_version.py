import warnings
from importlib.metadata import version as get_version

import httpx
from packaging import version


class UnsupportedVersionError(Exception):
    pass


def check_version(base_url):
    package_name = "gcapi"

    current_version = get_version(package_name)

    with httpx.Client() as client:
        response = client.get(f"{base_url}gcapi/")

        api_data = response.json()

        latest_version = api_data["latest_version"]
        lowest_supported_version = api_data["lowest_supported_version"]

    current_version_v = version.parse(current_version)
    latest_version_v = version.parse(latest_version)
    lowest_supported_version_v = version.parse(lowest_supported_version)

    if current_version_v < lowest_supported_version_v:
        raise UnsupportedVersionError(
            f"You are using {package_name} version {current_version}. "
            f"However, the platform only supports {lowest_supported_version} "
            "or newer. Upgrade via `pip install --upgrade {package_name}`",
        )

    if current_version_v < latest_version_v:
        warnings.warn(
            f"You are using {package_name} version {current_version}. "
            f"However, version {latest_version} is available. You should consider"
            f" upgrading via `pip install --upgrade {package_name}`",
            UserWarning,
            stacklevel=0,
        )
