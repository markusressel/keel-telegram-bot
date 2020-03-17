import logging
from typing import List

from pip._vendor import requests
from pip._vendor.requests.auth import HTTPBasicAuth

from keel_telegram_bot.const import REQUESTS_TIMEOUT

LOGGER = logging.getLogger(__name__)

GET = "get"
POST = "post"


class KeelApiClient:
    """
    Keel REST api client
    """

    def __init__(self, host: str, port: int, ssl: bool, user: str, password: str):
        self._host = host
        self._port = port
        self._ssl = ssl
        self._auth = HTTPBasicAuth(user, password)

        self._base_url = f"{'https' if ssl else 'http'}://{host}:{port}"

    def get_approvals(self, rejected: bool = None, archived: bool = None) -> List[dict]:
        """
        :param rejected: True for rejected, False for approved, None for all
        :param archived: True for archived, False for not archived, None for all
        :return: a list of all approvals matching criteria
        """
        response = self._do_request(GET, self._base_url + "/v1/approvals")

        if rejected is not None:
            response = list(filter(lambda x: x["rejected"] == rejected, response))
        if archived is not None:
            response = list(filter(lambda x: x["archived"] == archived, response))

        return response

    def approve(self, identifier: str, voter: str) -> None:
        """
        Approve a pending approval
        :param identifier: identifier for the approval request, something like "default/myimage:1.5.5"
        :param voter: name of the voter
        """
        self._do_request(POST, self._base_url + "/v1/approvals", json={
            "identifier": identifier,
            "action": "approve",
            "voter": voter,
        })

    def reject(self, identifier: str, voter: str) -> None:
        """
        Reject a pending approval
        :param identifier: identifier for the approval request, something like "default/myimage:1.5.5"
        :param voter: name of the voter
        """
        self._do_request(POST, self._base_url + "/v1/approvals", json={
            "identifier": identifier,
            "action": "reject",
            "voter": voter,
        })

    def delete(self, identifier: str, voter: str) -> None:
        """
        Delete a pending approval
        :param identifier: identifier for the approval request, something like "default/myimage:1.5.5"
        :param voter: name of the voter
        """
        self._do_request(POST, self._base_url + "/v1/approvals", json={
            "identifier": identifier,
            "action": "delete",
            "voter": voter,
        })

    def _do_request(self, method: str = GET, url: str = "/", params: dict = None,
                    json: dict = None) -> list or dict or None:
        """
        Executes a http request based on the given parameters

        :param method: the method to use (GET, POST)
        :param url: the url to use
        :param params: query parameters that will be appended to the url
        :param json: request body
        :return: the response parsed as a json
        """
        headers = []
        url = self._create_request_url(url, params)

        if method is GET:
            response = requests.get(url, headers=headers, auth=self._auth, json=json, timeout=REQUESTS_TIMEOUT)
        elif method is POST:
            response = requests.post(url, headers=headers, auth=self._auth, json=json, timeout=REQUESTS_TIMEOUT)
        else:
            raise ValueError("Unsupported method: {}".format(method))

        response.raise_for_status()
        # some responses do not return data so we just ignore the body in that case
        if len(response.content) > 0:
            return response.json()

    @staticmethod
    def _create_request_url(url: str, params: dict = None):
        """
        Adds query params to the given url

        :param url: the url to extend
        :param params: query params as a keyed dictionary
        :return: the url including the given query params
        """

        if params:
            first_param = True
            for k, v in sorted(params.items(), key=lambda entry: entry[0]):
                if not v:
                    # skip None values
                    continue

                if first_param:
                    url += '?'
                    first_param = False
                else:
                    url += '&'

                url += "%s=%s" % (k, v)

        return url
