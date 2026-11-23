REQUESTS_TIMEOUT = (5, 5)
# a poll of all images can take up to a minute
POLL_REQUESTS_TIMEOUT = (5, 90)
TELEGRAM_CAPTION_LENGTH_LIMIT = 200
TELEGRAM_CALLBACK_DATA_LIMIT = 64

# Commands
COMMAND_START = "start"
COMMAND_LIST_RESOURCES = ["resources"]
COMMAND_LIST_TRACKED = ["tracked"]
COMMAND_LIST_APPROVALS = ["approvals"]
COMMAND_UPDATE = ["update"]
COMMAND_POLL = ["poll"]
COMMAND_APPROVE = ["approve", "a"]
COMMAND_REJECT = ["reject", "r"]
COMMAND_DELETE = ["delete", "d"]
COMMAND_LIST_HELM_CHARTS = ["helmcharts", "hc"]
COMMAND_CHECK_HELM_CHARTS = ["helmcheck", "hcc"]
COMMAND_CHATID = "chatid"

COMMAND_STATS = 'stats'

COMMAND_HELP = ['help', 'h']
COMMAND_VERSION = ['version', 'v']
COMMAND_CONFIG = ['config', 'c']

CANCEL_KEYBOARD_COMMAND = "/cancel_keyboard"

# inline keyboard button data
BUTTON_DATA_NOTHING = "_"
BUTTON_DATA_APPROVE = "a"
BUTTON_DATA_REJECT = "r"
# helm chart buttons, followed by the chart version(s): "hu:1.2.3", "hi:2.0.0,1.3.0"
BUTTON_DATA_HELM_UPGRADE_PREFIX = "hu:"
BUTTON_DATA_HELM_IGNORE_PREFIX = "hi:"
# "Check now" button of approvals and notifications: "p:<identifier>", or only "p" if the identifier does not fit
# into the callback data, then it is taken from the remembered approval message or the text of the message
BUTTON_DATA_POLL = "p"
BUTTON_DATA_POLL_PREFIX = "p:"

# webserver
ENDPOINT_WEBHOOK = "/"
