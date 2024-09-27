from dataclasses import dataclass


@dataclass
class K8SStatus:
    """
    Status data class
    """
    replicas: int
    updated_replicas: int
    ready_replicas: int
    available_replicas: int
    unavailable_replicas: int

    @staticmethod
    def from_dict(data: dict):
        return K8SStatus(
            replicas=data["replicas"],
            updated_replicas=data["updatedReplicas"],
            ready_replicas=data["readyReplicas"],
            available_replicas=data["availableReplicas"],
            unavailable_replicas=data["unavailableReplicas"],
        )
