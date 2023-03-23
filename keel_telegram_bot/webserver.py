import asyncio
import json
import logging

import aiohttp
from aiohttp import web
from aiohttp.web_response import Response

from keel_telegram_bot.bot import KeelTelegramBot
from keel_telegram_bot.config import Config
from keel_telegram_bot.const import ENDPOINT_WEBHOOK

LOGGER = logging.getLogger(__name__)
routes = web.RouteTableDef()


class WebsocketServer:
    bot = None

    def __init__(self, config: Config, bot: KeelTelegramBot):
        self.config = config
        WebsocketServer.bot = bot

    async def start(self):
        host = "0.0.0.0"  # self.config.SERVER_HOST.value,
        port = 5000  # self.config.SERVER_PORT.value
        LOGGER.info(f"Starting webserver on {host}:{port} ...")

        app = self._create_app()
        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        site = aiohttp.web.TCPSite(
            runner,
            host=host,
            port=port,
        )
        await site.start()

        # wait forever
        return await asyncio.Event().wait()

    def _create_app(self) -> web.Application:
        app = web.Application(middlewares=[])
        app.add_routes(routes)
        return app

    # @app.route('/', methods=['GET', 'POST'])
    # @app.route('/<path:path>', methods=['GET', 'POST'])
    # @routes.get(ENDPOINT_WEBHOOK)
    @routes.post(ENDPOINT_WEBHOOK)
    # @time(REST_TIME_WEBHOOK)
    # @staticmethod
    async def catch_all(self) -> Response:
        if not self.can_read_body:
            LOGGER.error("Request has no body!")
            return Response(text="Failed to read request")
        body = await self.content.read()
        if len(body) <= 0:
            LOGGER.error("Request has no body!")
            return Response(text="Request body is empty!")

        data = json.loads(body)
        await WebsocketServer.bot.on_notification(data)
        return Response(text="OK")
