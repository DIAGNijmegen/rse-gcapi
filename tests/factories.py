import uuid

from gcapi.models import (
    Algorithm,
    ColorSpaceEnum,
    ComponentInterface,
    HyperlinkedComponentInterfaceValue,
    HyperlinkedImage,
)

pk_counter = 0


def _get_int_pk():
    global pk_counter

    current = pk_counter
    pk_counter += 1

    return current


def SocketFactory(**kwargs) -> ComponentInterface:  # noqa: N802
    pk = kwargs.get("pk") or _get_int_pk()
    ci = ComponentInterface(
        pk=pk,
        title=f"A title {pk}",
        description=None,
        kind="Image",
        slug=f"a-slug-{pk}",
        default_value=None,
        super_kind="Image",
        relative_path="images/dir_name",
        overlay_segments=None,
        look_up_table=None,
    )

    for key, value in kwargs.items():
        setattr(ci, key, value)

    return ci


def HyperlinkedComponentInterfaceValueFactory(  # noqa: N802
    **kwargs,
) -> HyperlinkedComponentInterfaceValue:
    pk = kwargs.get("pk") or _get_int_pk()

    hciv = HyperlinkedComponentInterfaceValue(
        pk=pk,
        interface=SocketFactory(),
        value=None,
        file=None,
        image=None,
    )

    for key, value in kwargs.items():
        setattr(hciv, key, value)

    return hciv


def HyperlinkedImageFactory(**kwargs) -> HyperlinkedImage:  # noqa: N802

    pk = kwargs.get("pk") or str(uuid.uuid4())
    image = HyperlinkedImage(
        pk=pk,
        name=f"a_filename_{pk}.mha",
        files=[],
        dicom_image_set=None,
        width=10,
        height=10,
        depth=None,
        color_space=ColorSpaceEnum.GRAY,
        modality=None,
        eye_choice=None,
        stereoscopic_choice=None,
        field_of_view=None,
        shape_without_color=[10, 10],
        shape=[10, 10],
        voxel_width_mm=None,
        voxel_height_mm=None,
        voxel_depth_mm=None,
        api_url=f"https://example.test/api/v1/cases/images/{pk}/",
        window_center=None,
        window_width=None,
        segments=None,
    )

    for key, value in kwargs.items():
        setattr(image, key, value)

    return image


def AlgorithmFactory(**kwargs) -> Algorithm:  # noqa: N802

    pk = kwargs.get("pk") or str(uuid.uuid4())
    slug = kwargs.get("slug") or "a-slug"

    alg = Algorithm(
        api_url=f"https://example.test/api/v1/algorithms/{pk}/",
        url=f"https://example.test/algorithms/{slug}",
        description=None,
        pk=pk,
        title="A title",
        logo="foo",
        slug=slug,
        average_duration=None,
        interfaces=[],
    )

    for key, value in kwargs.items():
        setattr(alg, key, value)

    return alg
