import enum


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

    @staticmethod
    def from_value(value: str):
        """
        Get the enum from a value
        :param value: the value to convert
        :return: the enum
        """
        for provider in Provider:
            if provider.value.lower() == value.lower():
                return provider
        raise Exception(f"Unknown provider value: {value}")


class Trigger(enum.Enum):
    """
    Enum for trigger types
    """
    Default = "default"
    Poll = "poll"
    Approval = "approval"


class SemverPolicyType(enum.Enum):
    """
    Enum for semver policy types
    """
    NNone = "none"
    All = "all"
    Major = "major"
    minor = "minor"
    Patch = "patch"

    @staticmethod
    def from_value(value: str):
        """
        Get the enum from a value
        :param value: the value to convert
        :return: the enum
        """
        for policy in SemverPolicyType:
            if policy.value.lower() == value.lower():
                return policy
        return SemverPolicyType.NNone
