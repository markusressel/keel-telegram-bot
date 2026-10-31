REQUESTS_TIMEOUT = (5, 5)
TELEGRAM_CAPTION_LENGTH_LIMIT = 200
TELEGRAM_CALLBACK_DATA_LIMIT = 64

# Commands
COMMAND_START = "start"
COMMAND_LIST_RESOURCES = ["resources"]
COMMAND_LIST_TRACKED = ["tracked"]
COMMAND_LIST_APPROVALS = ["approvals"]
COMMAND_UPDATE = ["update"]
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

# webserver
ENDPOINT_WEBHOOK = "/"
