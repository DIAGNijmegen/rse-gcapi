import uuid

from gcapi.models import ComponentInterface, SimpleImage

pk_counter = 0


def _get_int_pk():
    global pk_counter

    current = pk_counter
    pk_counter += 1

    return current


def ComponentInterfaceFactory(**kwargs) -> ComponentInterface:  # noqa: N802
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


def SimpleImageFactory(**kwargs) -> SimpleImage:  # noqa: N802

    pk = kwargs.get("pk") or str(uuid.uuid4())
    si = SimpleImage(pk=pk, name=f"a_filename_{pk}.mha")

    for key, value in kwargs.items():
        setattr(si, key, value)

    return si
