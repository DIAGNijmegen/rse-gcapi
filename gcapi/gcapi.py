# -*- coding: utf-8 -*-

from requests import Session


class Client(Session):
    def __init__(
        self, token=None, base_url="https://grand-challenge.org/api/v1/", verify=True
    ):
        super(Client, self).__init__()

        self.headers.update({"Accept": "application/json"})

        if token:
            self.headers.update({"Authorization": "TOKEN {}".format(token)})
        else:
            raise RuntimeError("Token must be set")

        self._base_url = base_url
        if not self._base_url.startswith("https://"):
            raise RuntimeError("Base URL must be https")

        # Should we verify the servers SSL certificates?
        self._verify = verify
