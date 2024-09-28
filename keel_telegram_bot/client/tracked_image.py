from attr import dataclass

from keel_telegram_bot.client.types import Trigger, Policy


@dataclass
class TrackedImage:
    image: str
    trigger: Trigger
    poll_schedule: str
    provider: str
    namespace: str
    policy: Policy
    registry: str

    @staticmethod
    def from_dict(d: dict):
        return TrackedImage(
            image=d["image"],
            trigger=Trigger.from_value(d["trigger"]),
            poll_schedule=d["pollSchedule"],
            provider=d["provider"],
            namespace=d["namespace"],
            policy=Policy.from_value(d["policy"]),
            registry=d["registry"],
        )

    def to_dict(self):
        return {
            "image": self.image,
            "trigger": self.trigger,
            "pollSchedule": self.poll_schedule,
            "provider": self.provider,
            "namespace": self.namespace,
            "policy": self.policy,
            "registry": self.registry,
        }
