import enum
import logging
from collections import namedtuple
from typing import List, Optional

import requests
from requests import HTTPError
from requests.auth import HTTPBasicAuth

from keel_telegram_bot.client.approval import Approval
from keel_telegram_bot.client.daily_stats import DailyStats
from keel_telegram_bot.client.poll_result import PollResult, PollBusyError, PollNotWatchedError, \
    PollUnsupportedError
from keel_telegram_bot.client.resource import Resource
from keel_telegram_bot.client.tracked_image import TrackedImage
from keel_telegram_bot.client.types import Action, Provider, Trigger, Policy, PollSchedule
from keel_telegram_bot.const import REQUESTS_TIMEOUT, POLL_REQUESTS_TIMEOUT

LOGGER = logging.getLogger(__name__)


class HttpMethod(namedtuple('HttpMethod', 'name method'), enum.Enum):
    GET = "get", requests.get
    POST = "post", requests.post
    PUT = "put", requests.put


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

    def get_resources(self) -> List[Resource]:
        """
        Returns a list of all resources
        """
        response = self._do_request(HttpMethod.GET, self._base_url + "/v1/resources")
        result = [Resource.from_dict(resource) for resource in response]
        return result

    def get_resource(self, identifier: str) -> Optional[Resource]:
        """
        Returns a resource by identifier
        """
        resources = self.get_resources()
        for resource in resources:
            if resource.identifier == identifier:
                return resource
        return None

    def get_tracked_images(self) -> List[TrackedImage]:
        """
        Returns a list of all tracked images
        """
        response = self._do_request(HttpMethod.GET, self._base_url + "/v1/tracked")
        result = [TrackedImage.from_dict(tracked) for tracked in response]
        return result

    def get_tracked_image(self, namespace: str, image: str) -> Optional[TrackedImage]:
        """
        Returns a list of all tracked images
        """
        trecked_images = self.get_tracked_images()
        for tracked_image in trecked_images:
            if tracked_image.namespace == namespace and tracked_image.image == image:
                return tracked_image
        return None

    def set_tracked(self, identifier: str, provider: Provider, trigger: Trigger,
                    schedule: Optional[PollSchedule]) -> None:
        """
        Set the tracking properties for an image
        :param identifier: the identifier of the image
        :param provider: the provider of the image
        :param trigger: the trigger of the image
        :param schedule: the schedule of the image
        """
        self._do_request(HttpMethod.PUT, self._base_url + "/v1/tracked", json={
            "identifier": identifier,
            "provider": provider.value,
            "trigger": trigger.value,
            "schedule": schedule.value,
        })

    def set_required_approvals_count(
        self, identifier: str, votes_required: int
    ) -> None:
        """
        Set the required approvals count for an image
        :param identifier: the identifier of the image
        :param votes_required: the required approvals count
        """
        resource = self.get_resource(identifier)
        self._do_request(HttpMethod.PUT, self._base_url + "/v1/approvals", json={
            "identifier": identifier,
            "provider": resource.provider.value,
            "votesRequired": votes_required,
        })

    def set_policy(self, identifier: str, policy: Policy) -> None:
        """
        Set the policy for an image
        :param identifier: the identifier of the image
        :param policy: the policy of the image
        """
        resource = self.get_resource(identifier)
        self._do_request(HttpMethod.PUT, self._base_url + "/v1/policies", json={
            "identifier": identifier,
            "provider": resource.provider.value,
            "policy": policy.value,
        })

    def set_schedule(self, identifier: str, schedule: PollSchedule, trigger: Trigger) -> None:
        """
        Set the polling schedule for an image
        :param identifier: the identifier of the image
        :param schedule: the schedule of the image
        :param trigger: the trigger of the image
        """
        resource = self.get_resource(identifier)
        self.set_tracked(identifier, resource.provider, trigger, schedule)

    def set_trigger(self, identifier: str, trigger: Trigger) -> None:
        """
        Set the trigger for an image
        :param identifier: the identifier of the image
        :param trigger: the trigger of the image
        """
        resource = self.get_resource(identifier)
        self._do_request(HttpMethod.PUT, self._base_url + "/v1/tracked", json={
            "identifier": identifier,
            "provider": resource.provider.value,
            "trigger": trigger.value,
        })

    def get_approvals(self, rejected: bool = None, archived: bool = None) -> List[Approval]:
        """
        :param rejected: True for rejected, False for approved, None for all
        :param archived: True for archived, False for not archived, None for all
        :return: a list of all approvals matching criteria
        """
        response = self._do_request(HttpMethod.GET, self._base_url + "/v1/approvals")
        result = [Approval.from_dict(approval) for approval in response]

        if rejected is not None:
            result = list(filter(lambda x: x.rejected == rejected, result))
        if archived is not None:
            result = list(filter(lambda x: x.archived == archived, result))

        return result

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
        self._do_request(HttpMethod.POST, self._base_url + "/v1/approvals", json={
            "id": id,
            "identifier": identifier,
            "voter": voter,
            "action": action.value,
        })

    def get_stats(self) -> DailyStats:
        """
        Returns the stats
        """
        result = self._do_request(HttpMethod.GET, self._base_url + "/v1/stats")
        return DailyStats.from_dict(result)

    def poll(self, identifier: Optional[str] = None, image: Optional[str] = None) -> List[PollResult]:
        """
        Asks Keel to poll the registry now, instead of waiting for the poll schedule.
        Needs a Keel build with the POST /v1/poll endpoint. A newer version found is handed to Keel, which
        then updates or asks for approval as usual. This can take up to a minute.
        :param identifier: resource identifier (as in /v1/resources), f.ex. "deployment/default/myapp"
        :param image: image repository, f.ex. "ghcr.io/me/myapp"
        (neither identifier nor image: poll all watched images)
        :return: one result per polled image
        :raises PollNotWatchedError: the resource or image is not watched by the poll trigger
        :raises PollBusyError: a poll of all images is running already
        :raises PollUnsupportedError: Keel has no POST /v1/poll endpoint
        """
        if identifier is not None and image is not None:
            raise ValueError("Use either identifier or image, not both")
        body = {}
        if identifier is not None:
            body["identifier"] = identifier
        if image is not None:
            body["image"] = image

        try:
            response = self._do_request(HttpMethod.POST, self._base_url + "/v1/poll", json=body,
                                        timeout=POLL_REQUESTS_TIMEOUT)
        except HTTPError as ex:
            status = ex.response.status_code
            error = self._get_error_message(ex.response)
            if status == 404:
                if error is None:
                    # the route itself does not exist, a plain "404 page not found" of the router
                    raise PollUnsupportedError("Keel has no POST /v1/poll endpoint") from ex
                raise PollNotWatchedError(error) from ex
            if status == 405:
                raise PollUnsupportedError("Keel has no POST /v1/poll endpoint") from ex
            if status == 429:
                raise PollBusyError(error or "A poll of all images is running already") from ex
            raise

        results = (response or {}).get("results") or []
        return [PollResult.from_dict(x) for x in results]

    @staticmethod
    def _get_error_message(response) -> Optional[str]:
        """
        :return: the "error" of a JSON error response, None if the response is not one
        """
        try:
            data = response.json()
        except ValueError:
            return None
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            return data["error"]
        return None

    def _do_request(
        self,
        method: HttpMethod = HttpMethod.GET,
        url: str = "/",
        params: dict = None,
        json: dict = None,
        timeout=REQUESTS_TIMEOUT,
    ) -> Optional[list | dict]:
        """
        Executes an http request based on the given parameters

        :param method: the method to use (GET, PUT, POST)
        :param url: the url to use
        :param params: query parameters that will be appended to the url
        :param json: request body
        :param timeout: (connect, read) timeout in seconds
        :return: the response parsed as a json
        """
        headers = []
        url = self._create_request_url(url, params)

        response = method.method(url, headers=headers, auth=self._auth, json=json, timeout=timeout)

        if response.status_code >= 400:
            LOGGER.debug("Request to %s returned status code %s: %s", url, response.status_code, response.text)
        response.raise_for_status()
        # some responses do not return data so we just ignore the body in that case
        if len(response.content) > 0 and response.content != b"null":
            return response.json()
        return None

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
