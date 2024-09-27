from typing import List, Dict

from attr import dataclass

from keel_telegram_bot.client.k8s_status import K8SStatus
from keel_telegram_bot.client.types import Provider, SemverPolicyType


@dataclass
class Resource:
    """
    Resource data class
    """
    provider: Provider
    identifier: str
    name: str
    namespace: str
    kind: str
    policy: SemverPolicyType
    images: List[str]
    labels: Dict[str, str]
    annotations: Dict[str, str]
    status: K8SStatus

    @staticmethod
    def from_dict(data: dict):
        return Resource(
            provider=Provider(data["provider"]),
            identifier=data["identifier"],
            name=data["name"],
            namespace=data["namespace"],
            kind=data["kind"],
            policy=SemverPolicyType(data["policy"]),
            images=data["images"],
            labels=data["labels"],
            annotations=data["annotations"],
            status=K8SStatus.from_dict(data["status"]),
        )
