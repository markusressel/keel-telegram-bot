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
