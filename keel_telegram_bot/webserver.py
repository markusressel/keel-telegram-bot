import json

from flask import Flask, request

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.config import Config

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def catch_all(path: str = None):
    # TODO: handle incoming requests, specifically from Keel
    if request.data is not None:
        data = json.loads(request.data)
        WebsocketServer.bot.notify(data)
    return "OK"


class WebsocketServer:
    bot = None

    def __init__(self, config: Config, bot: KeelTelegramBot):
        self.config = config
        WebsocketServer.bot = bot

    def run(self):
        app.run(
            host="0.0.0.0",
            port=5000
        )
