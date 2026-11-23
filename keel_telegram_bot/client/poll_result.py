from dataclasses import dataclass
from typing import Optional


@dataclass
class PollResult:
    """
    Result of an on-demand registry poll for a single image (POST /v1/poll)
    """
    image: str
    # the poll found a newer version and handed it to Keel, which updates or asks for approval
    submitted: bool
    # empty if the poll worked
    error: str = ""
    # the new tag, if Keel tells
    tag: Optional[str] = None

    @staticmethod
    def from_dict(data: dict):
        return PollResult(
            image=data.get("image", ""),
            submitted=bool(data.get("submitted", False)),
            error=data.get("error") or "",
            tag=data.get("tag") or None,
        )


class PollError(Exception):
    """
    Base class of errors of POST /v1/poll
    """


class PollNotWatchedError(PollError):
    """
    The resource or image is not watched by the poll trigger of Keel (404 with an error message)
    """


class PollBusyError(PollError):
    """
    A poll of all images is running already (429)
    """


class PollUnsupportedError(PollError):
    """
    Keel has no POST /v1/poll endpoint (404 without the JSON error of the endpoint, or 405)
    """
