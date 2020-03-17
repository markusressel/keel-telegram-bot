import json

from flask import Flask, request

from keel_telegram_bot.config import Config

app = Flask(__name__)
config = Config()


@app.route('/', methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def catch_all():
    # TODO: handle incoming requests, specifically from Keel
    # TODO: send notification content to telegram
    data = json.loads(request.data)
    print(f"Data: {data}")
    return "OK"
