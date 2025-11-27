import gcapi.models

SocketValuePostSet = gcapi.models.DisplaySetPost | gcapi.models.ArchiveItemPost


class UnsetType:
    pass


Unset = UnsetType()
