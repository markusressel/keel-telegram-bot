import enum
import logging
from typing import List

import requests
from requests.auth import HTTPBasicAuth

from keel_telegram_bot.const import REQUESTS_TIMEOUT

LOGGER = logging.getLogger(__name__)

GET = "get"
POST = "post"
PUT = "put"


class Action(enum.Enum):
    """
    Enum for action types
    """
    Approve = "approve"
    Reject = "reject"
    Delete = "delete"
    Archive = "archive"


class Provider(enum.Enum):
    """
    Enum for provider types
    """
    Kubernetes = "kubernetes"
    Helm = "helm"


class Trigger(enum.Enum):
    """
    Enum for trigger types
    """
    Default = "default"
    Poll = "poll"


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

    def get_resources(self) -> List[dict]:
        """
        Returns a list of all resources
        """
        return self._do_request(GET, self._base_url + "/v1/resources")

    def get_tracked(self) -> List[dict]:
        """
        Returns a list of all tracked images
        """
        return self._do_request(GET, self._base_url + "/v1/tracked")

    def set_tracked(self, identifier: str, provider: Provider, trigger: Trigger, schedule: str or None) -> None:
        """
        Set the tracking properties for an image
        :param identifier: the identifier of the image
        :param provider: the provider of the image
        :param trigger: the trigger of the image
        :param schedule: the schedule of the image
        """
        self._do_request(PUT, self._base_url + "/v1/tracked", json={
            "identifier": identifier,
            "provider": provider.value,
            "trigger": trigger.value,
            "schedule": schedule,
        })

    def set_required_approvals_count(
        self, identifier: str, provider: Provider, votes_required: int
    ) -> None:
        """
        Set the required approvals count for an image
        :param identifier: the identifier of the image
        :param provider: the name of the voter
        :param votes_required: the required approvals count
        """
        self._do_request(PUT, self._base_url + "/v1/approvals", json={
            "identifier": identifier,
            "provider": provider.value,
            "votesRequired": votes_required,
        })

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

    def approve(self, id: str, identifier: str, voter: str) -> None:
        """
        Approve a pending approval
        :param id: item id
        :param identifier: identifier for the approval request, something like "default/myimage:1.5.5"
        :param voter: name of the voter
        """
        self._run_approval_action(id, identifier, voter, Action.Approve)

    def reject(self, id: str, identifier: str, voter: str) -> None:
        """
        Reject a pending approval
        :param id: item id
        :param identifier: identifier for the approval request, something like "default/myimage:1.5.5"
        :param voter: name of the voter
        """
        self._run_approval_action(id, identifier, voter, Action.Reject)

    def delete(self, id: str, identifier: str, voter: str) -> None:
        """
        Delete a pending approval
        :param id: item id
        :param identifier: identifier for the approval request, something like "default/myimage:1.5.5"
        :param voter: name of the voter
        """
        self._run_approval_action(id, identifier, voter, Action.Delete)

    def _run_approval_action(self, id: str, identifier: str, voter: str, action: Action) -> None:
        """
        Perform an action on a pending approval
        :param id: item id
        :param identifier: identifier for the approval request, something like "default/myimage:1.5.5"
        :param voter: name of the voter
        :param action: the action to perform
        """
        self._do_request(POST, self._base_url + "/v1/approvals", json={
            "id": id,
            "identifier": identifier,
            "voter": voter,
            "action": action.value,
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
            method = requests.get
        elif method is POST:
            method = requests.post
        else:
            raise ValueError("Unsupported method: {}".format(method))

        response = method(url, headers=headers, auth=self._auth, json=json, timeout=REQUESTS_TIMEOUT)

        response.raise_for_status()
        # some responses do not return data so we just ignore the body in that case
        if len(response.content) > 0 and response.content != b"null":
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
