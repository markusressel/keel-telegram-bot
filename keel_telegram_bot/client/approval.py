from dataclasses import dataclass
from typing import List

from keel_telegram_bot.client.types import Provider


@dataclass
class Approval:
    """
    Approval data class
    """
    id: str
    archived: bool
    provider: Provider
    identifier: str
    event: str
    message: str
    currentVersion: str
    newVersion: str
    digest: str
    votesRequired: int
    votesReceived: int
    voters: List[str]
    rejected: bool
    deadline: str
    createdAt: str
    updatedAt: str

    @staticmethod
    def from_dict(data: dict):
        return Approval(
            id=data["id"],
            archived=data["archived"],
            provider=Provider(data["provider"]),
            identifier=data["identifier"],
            event=data["event"],
            message=data["message"],
            currentVersion=data["currentVersion"],
            newVersion=data["newVersion"],
            digest=data["digest"],
            votesRequired=data["votesRequired"],
            votesReceived=data["votesReceived"],
            voters=data["voters"],
            rejected=data["rejected"],
            deadline=data["deadline"],
            createdAt=data["createdAt"],
            updatedAt=data["updatedAt"],
        )
