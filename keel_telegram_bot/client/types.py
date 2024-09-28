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
    Default = "default"
    Poll = "poll"
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
        else:
            return SemverPolicyType.from_value(value)

    @abc.abstractmethod
    def __str__(self):
        raise NotImplementedError()


class SemverPolicyType(enum.Enum, Policy):
    """
    Enum for semver policy types
    """
    NNone = "none"
    All = "all"
    Major = "major"
    Minor = "minor"
    Patch = "patch"
    Force = "force"

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

    def __str__(self):
        return self.value


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
