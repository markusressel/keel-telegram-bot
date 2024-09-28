import abc
import enum
import re
from abc import ABC
from datetime import timedelta

from keel_telegram_bot.client import parse_golang_duration, timedelta_to_golang_duration


class PollSchedule:
    """
    Poll schedule
    """

    def __init__(self, interval: timedelta):
        self.interval = interval

    @staticmethod
    def from_value(value: str):
        """
        Get the enum from a value
        :param value: the value to convert
        :return: the enum
        """
        if value.startswith("@every "):
            value = value.split(" ")[1]
        duration = parse_golang_duration(value)
        return PollSchedule(duration)

    def value(self):
        return self.__str__()

    def __str__(self):
        return f"@every {timedelta_to_golang_duration(self.interval)}"


class Action(enum.Enum):
    """
    Enum for action types
    """
    Approve = "approve"
    Reject = "reject"
    Delete = "delete"
    Archive = "archive"

    def __str__(self):
        return self.value


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

    def __str__(self):
        return self.value


class Trigger(enum.Enum):
    """
    Enum for trigger types
    """
    # Default means there is no polling.
    Default = "default"
    # Poll means the latest image version is polled regularly, based on the set pollSchedule.
    Poll = "poll"
    # TODO: figure out what this is for
    Approval = "approval"

    @staticmethod
    def from_value(value: str):
        """
        Get the enum from a value
        :param value: the value to convert
        :return: the enum
        """
        for trigger in Trigger:
            if trigger.value.lower() == value.lower():
                return trigger
        raise Exception(f"Unknown trigger value: {value}")

    def __str__(self):
        return self.value


class Policy(ABC):

    @staticmethod
    def from_value(value: str):
        """
        Get the enum from a value
        :param value: the value to convert
        :return: the enum
        """
        if value.startswith("glob:"):
            return GlobPolicy(value[5:])
        elif value.startswith("regexp:"):
            return RegexPolicy(re.compile(value[7:], re.IGNORECASE))
        elif value == "never":
            return NeverPolicy()
        else:
            return SemverPolicy.from_value(value)

    @property
    def value(self):
        return self.__str__()

    @abc.abstractmethod
    def __str__(self):
        raise NotImplementedError()


class NeverPolicy(Policy):
    """
    Policy for never matching
    """

    def __str__(self):
        return "never"

class SemverPolicyType(enum.Enum):
    """
    Enum for semver policy types
    """
    NNone = "none"
    All = "all"
    Major = "major"
    Minor = "minor"
    Patch = "patch"
    Force = "force"


class SemverPolicy(Policy):
    """
    Enum for semver policy types
    """

    def __init__(self, policy_type: SemverPolicyType):
        self._policy_type = policy_type

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
        return SemverPolicy(SemverPolicyType.NNone)

    def __str__(self):
        return self._policy_type.value


class GlobPolicy(Policy):
    """
    Policy for glob matching
    """

    def __init__(self, pattern: str):
        self._pattern = pattern

    def __str__(self):
        return f"glob:{self._pattern}"


class RegexPolicy(Policy):
    """
    Policy for Regex matching
    """

    def __init__(self, pattern: re.Pattern):
        self._pattern = pattern

    def __str__(self):
        return f"regexp:{self._pattern.pattern}"
