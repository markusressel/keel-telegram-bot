from prometheus_client import Summary, Counter
from prometheus_client.metrics import MetricWrapperBase

from keel_telegram_bot.const import *

COMMAND_TIME = Summary('command_processing_seconds', 'Time spent in a command handler', ['command'])
COMMAND_TIME_START = COMMAND_TIME.labels(command=COMMAND_START)
COMMAND_TIME_LIST_RESOURCES = COMMAND_TIME.labels(command=COMMAND_LIST_RESOURCES[0])
COMMAND_TIME_LIST_TRACKED = COMMAND_TIME.labels(command=COMMAND_LIST_TRACKED[0])
COMMAND_TIME_LIST_APPROVALS = COMMAND_TIME.labels(command=COMMAND_LIST_APPROVALS[0])
COMMAND_TIME_APPROVE = COMMAND_TIME.labels(command=COMMAND_APPROVE[0])
COMMAND_TIME_REJECT = COMMAND_TIME.labels(command=COMMAND_REJECT[0])
COMMAND_TIME_DELETE = COMMAND_TIME.labels(command=COMMAND_DELETE[0])
COMMAND_TIME_STATS = COMMAND_TIME.labels(command=COMMAND_STATS)

WATCHER_TIME = Summary('watcher_processing_seconds', 'Time spent in a watcher', ['type'])
APPROVAL_WATCHER_TIME = WATCHER_TIME.labels(type="approval")

NEW_PENDING_APPROVAL_COUNTER = Counter('keel_new_pending_approval',
                                       'Counts new pending approvals recognized by this bot')

REST_TIME = Summary('rest_endpoint_processing_seconds', 'Time spent in a rest command handler', ['endpoint'])
REST_TIME_WEBHOOK = REST_TIME.labels(endpoint=ENDPOINT_WEBHOOK)

KEEL_NOTIFICATION_COUNTER = Counter('keel_notifications', 'Counts notifications received from keel')
KEEL_APPROVAL_ACTION_COUNTER = Counter('keel_approval_action_counter',
                                       'Counts approval notificaion actions', ['action', 'identifier'])


def get_metrics() -> []:
    entries = set()
    for name, obj in globals().items():
        if isinstance(obj, MetricWrapperBase):
            entries.add(obj)

    return list(entries)


def format_metrics() -> str:
    def format_sample(sample):
        result = "  "
        if len(sample[0]) > 0:
            result += str(sample[0])
        if len(sample[1]) > 0:
            result += str(sample[1])

        if len(result) > 0:
            result += " "
        result += str(sample[2])

        return result

    def format_samples(samples):
        return "\n".join(list(map(format_sample, samples)))

    def format_metric(metric):
        name = metric._name
        samples = list(metric._samples())
        samples_text = format_samples(samples)

        return "{}:\n{}".format(name, samples_text)

    return "\n\n".join(map(format_metric, get_metrics()))
