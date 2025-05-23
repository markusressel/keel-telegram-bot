import asyncio
import logging
import re
from typing import Dict, List

from container_app_conf.formatter.toml import TomlFormatter
from requests import HTTPError
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import CommandHandler, filters, MessageHandler, CallbackQueryHandler, \
    ApplicationBuilder, ContextTypes
from telegram_click.argument import Argument, Flag, Selection
from telegram_click.decorator import command
from telegram_click.error_handler import DefaultErrorHandler

from keel_telegram_bot import util
from keel_telegram_bot.bot.permissions import CONFIG_ADMINS, CONFIGURED_CHAT_ID
from keel_telegram_bot.bot.reply_keyboard_handler import ReplyKeyboardHandler
from keel_telegram_bot.client.api_client import KeelApiClient
from keel_telegram_bot.client.approval import Approval
from keel_telegram_bot.client.resource import Resource
from keel_telegram_bot.client.tracked_image import TrackedImage
from keel_telegram_bot.client.types import SemverPolicy, Policy, PollSchedule, SemverPolicyType, Trigger
from keel_telegram_bot.config import Config
from keel_telegram_bot.stats import *
from keel_telegram_bot.util import send_message, approval_to_str, resource_to_str, tracked_image_to_str

LOGGER = logging.getLogger(__name__)


class CustomErrorHandler(DefaultErrorHandler):

    def __init__(self):
        super().__init__(silent_denial=True, print_error=True)


class KeelTelegramBot:
    """
    The main entry class of the keel telegram bot
    """

    def __init__(self, config: Config, api_client: KeelApiClient):
        """
        Creates an instance.
        :param config: configuration object
        """
        self._config = config
        self._api_client = api_client
        self._message_map = {}

        self._response_handler = ReplyKeyboardHandler()

        self._app = ApplicationBuilder().token(self._config.TELEGRAM_BOT_TOKEN.value).build()

        handler_groups = {
            0: [CallbackQueryHandler(callback=self._inline_keyboard_click_callback)],
            1: [
                CommandHandler(COMMAND_START,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._start_callback),
                CommandHandler(COMMAND_LIST_RESOURCES,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._list_resources_callback),
                CommandHandler(COMMAND_LIST_TRACKED,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._list_tracked_callback),
                CommandHandler(COMMAND_LIST_APPROVALS,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._list_approvals_callback),
                CommandHandler(COMMAND_UPDATE,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._update_callback),
                CommandHandler(COMMAND_APPROVE,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._approve_callback),
                CommandHandler(COMMAND_REJECT,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._reject_callback),
                CommandHandler(COMMAND_DELETE,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._delete_callback),
                CommandHandler(COMMAND_STATS,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._stats_callback),
                CommandHandler(COMMAND_CHATID,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._chatid_callback),

                CommandHandler(COMMAND_HELP,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._help_callback),
                CommandHandler(COMMAND_CONFIG,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._config_callback),
                CommandHandler(COMMAND_VERSION,
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._version_callback),
                CommandHandler(CANCEL_KEYBOARD_COMMAND[1:],
                               filters=(~ filters.REPLY) & (~ filters.FORWARDED),
                               callback=self._response_handler.cancel_keyboard_callback),
                # unknown command handler
                MessageHandler(
                    filters=filters.COMMAND & (~ filters.FORWARDED),
                    callback=self._unknown_command_callback),
                MessageHandler(
                    filters=(~ filters.FORWARDED),
                    callback=self._any_message_callback),
            ]
        }

        for group, handlers in handler_groups.items():
            for handler in handlers:
                self._app.add_handler(handler, group=group)

    @property
    def bot(self):
        return self._app.bot

    async def start(self):
        """
        Starts up the bot.
        """
        await self._app.initialize()
        LOGGER.debug(f"Using bot id '{self._app.bot.id}' ({self._app.bot.name})")
        await self._app.start()
        await self._app.updater.start_polling()

    def stop(self):
        """
        Shuts down the bot.
        """
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._app.shutdown())

    @COMMAND_TIME_START.time()
    async def _start_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Welcomes a new user with a greeting message
        :param update: the chat update object
        :param context: telegram context
        """
        bot = context.bot
        chat_id = update.effective_chat.id
        user_first_name = update.effective_user.first_name

        if not CONFIG_ADMINS.evaluate(update, context):
            await send_message(bot, chat_id, "Sorry, you do not have permissions to use this bot.")
            return

        await send_message(bot, chat_id,
                           f"Welcome {user_first_name},\nthis is your keel-telegram-bot instance, ready to go!")

    @COMMAND_TIME_LIST_RESOURCES.time()
    @command(name=COMMAND_LIST_RESOURCES,
             description="List all resources.",
             arguments=[
                 Argument(name=["glob", "f"], description="Filter entries using the given text",
                          example="	deployment/myimage", optional=True),
                 Argument(name=["limit", "l"], description="Limit the number of entries", type=int,
                          example="10", optional=True, default=10),
                 Flag(name=["tracked", "t"], description="Only list tracked resources"),
             ],
             error_handler=CustomErrorHandler(),
             permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS)
    async def _list_resources_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
        glob: str or None,
        limit: int,
        tracked: bool,
    ) -> None:
        """
        Lists all available resources
        :param update: the chat update object
        :param context: telegram context
        :param glob: (optional) filter glob
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        def filter_resources_by(resources: List[Resource], glob: str or None, tracked: bool) -> List[Resource]:
            result = resources
            if glob is not None:
                result = list(filter(
                    lambda x: re.search(glob, x.name) or re.search(glob, x.namespace) or re.search(glob,
                                                                                                   x.policy.value) or any(
                        list(map(lambda y: re.search(glob, y), x.images))), resources))

            if tracked:
                result = list(filter(lambda x: x.policy != SemverPolicy(SemverPolicyType.NNone), result))

            # apply limit
            result = result[:limit]

            return result

        items = self._api_client.get_resources()
        filtered_items = filter_resources_by(items, glob, tracked)

        formatted_message = "\n\n".join(
            list(map(lambda x: resource_to_str(x), filtered_items))
        )

        await send_message(bot, chat_id, formatted_message, reply_to=message.message_id)

    @COMMAND_TIME_LIST_TRACKED.time()
    @command(name=COMMAND_LIST_TRACKED,
             description="List tracked images.",
             arguments=[
                 Argument(name=["glob", "f"], description="Filter entries using the given text",
                          example="	deployment/myimage", optional=True),
                 Argument(name=["limit", "l"], description="Limit the number of entries", type=int,
                          example="10", optional=True, default=10),
             ],
             error_handler=CustomErrorHandler(),
             permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS)
    async def _list_tracked_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
        glob: str or None,
        limit: int,
    ) -> None:
        """
        List tracked images
        :param update: the chat update object
        :param context: telegram context
        :param glob: (optional) filter glob
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        def filter_tracked_images_by(images: List[TrackedImage], glob: str or None) -> List[TrackedImage]:
            result = images
            if glob is not None:
                result = list(filter(
                    lambda x: re.search(glob, x.image) or
                              re.search(glob, x.namespace) or
                              re.search(glob, x.policy.value)
                ))

                # apply limit
                result = result[:limit]

            return result

        items = self._api_client.get_tracked_images()
        filtered_items = filter_tracked_images_by(items, glob)

        formatted_message = "\n\n".join(
            list(map(lambda x: tracked_image_to_str(x), filtered_items))
        )

        await send_message(bot, chat_id, formatted_message, reply_to=message.message_id)

    @COMMAND_TIME_LIST_APPROVALS.time()
    @command(name=COMMAND_LIST_APPROVALS,
             description="List pending approvals",
             arguments=[
                 Argument(name=["limit", "l"], description="Limit the number of entries per category", type=int,
                          example="3", optional=True, default=3),
                 Flag(name=["archived", "h"], description="Include archived items"),
                 Flag(name=["approved", "a"], description="Include approved items"),
                 Flag(name=["rejected", "r"], description="Include rejected items"),
             ],
             error_handler=CustomErrorHandler(),
             permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS)
    async def _list_approvals_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
        limit: int,
        archived: bool, approved: bool, rejected: bool) -> None:
        """
        List pending approvals
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        items = self._api_client.get_approvals()
        items = list(filter(lambda x: not self._is_filtered_for(chat_id, x.identifier), items))

        rejected_items = list(filter(lambda x: x.rejected, items))
        archived_items = list(filter(lambda x: x.archived, items))
        pending_items = list(filter(
            lambda x: x not in archived_items and x not in rejected_items
                      and x.votesReceived < x.votesRequired, items))
        approved_items = list(
            filter(lambda x: x not in rejected_items and x not in archived_items and x not in pending_items, items))

        rejected_items_limited = rejected_items[:limit]
        archived_items_limited = archived_items[:limit]
        pending_items_limited = pending_items[:limit]
        approved_items_limited = approved_items[:limit]

        lines = []
        if archived:
            lines.append("\n".join([
                f"<b>=== Archived ({len(archived_items_limited)}/{len(archived_items)}) ===</b>",
                "",
                "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), archived_items)))
            ]).strip())

        if approved:
            lines.append("\n".join([
                f"<b>=== Approved ({len(approved_items_limited)}/{len(approved_items)}) ===</b>",
                "",
                "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), approved_items))),
            ]).strip())

        if rejected:
            lines.append("\n".join([
                f"<b>=== Rejected ({len(rejected_items_limited)}{len(rejected_items)}) ===</b>",
                "",
                "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), rejected_items))),
            ]).strip())

        lines.append("\n".join([
            f"<b>=== Pending ({len(pending_items_limited)}/{len(pending_items)}) ===</b>",
            "",
            "\n\n".join(list(map(lambda x: "> " + approval_to_str(x), pending_items))),
        ]))

        text = "\n\n".join(lines).strip()
        await send_message(bot, chat_id, text, reply_to=message.message_id, parse_mode="HTML")

    @COMMAND_TIME_UPDATE.time()
    @command(name=COMMAND_UPDATE,
             description="Update the properties of a resource",
             arguments=[
                 Argument(name=["identifier", "i"], description="Resource identifier",
                          example="daemonset/docker-proxy/docker-proxy"),
                 Argument(name=["count", "c"], description="Approval count", example="2", type=int, optional=True),
                 Argument(name=["policy", "p"], description="Policy", example="all", type=Policy,
                          converter=lambda x: Policy.from_value(x), optional=True),
                 Argument(name=["schedule", "s"], description="Schedule to use for polling image versions",
                          example="24h", type=PollSchedule,
                          converter=lambda x: PollSchedule.from_value(x), optional=True),
                 Selection(name=["trigger", "t"], description="Trigger to use for polling image versions",
                           type=Trigger, converter=lambda x: Trigger.from_value(x),
                           allowed_values=[Trigger.Default, Trigger.Poll, Trigger.Approval], optional=True),
             ],
             error_handler=CustomErrorHandler(),
             permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS)
    async def _update_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
        identifier: str,
        count: int or None,
        policy: Policy or None,
        schedule: PollSchedule or None,
        trigger: Trigger or None,
    ) -> None:
        """
        Set the required approval count for a resource
        """
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        # NOTE: validation needs to happen before entering the keyboard callback, because errors in the keyboard callback
        # are currently not propagated properly.
        if schedule is not None:
            if trigger is None:
                raise ValueError("Cannot set schedule without trigger")

        async def execute(update: Update, context: ContextTypes.DEFAULT_TYPE, item: Resource, data: dict):
            bot = context.bot
            message = update.effective_message
            chat_id = update.effective_chat.id

            if count is not None:
                self._api_client.set_required_approvals_count(
                    identifier=item.identifier,
                    votes_required=count,
                )

            if policy is not None:
                self._api_client.set_policy(
                    identifier=item.identifier,
                    policy=policy,
                )

            if schedule is not None:
                self._api_client.set_schedule(
                    identifier=item.identifier,
                    schedule=schedule,
                    trigger=trigger,
                )
            else:
                if trigger is not None:
                    self._api_client.set_trigger(
                        identifier=item.identifier,
                        trigger=trigger,
                    )

            resource = self._api_client.get_resource(identifier=item.identifier)
            resource_lines = resource_to_str(resource)
            text = resource_lines

            await send_message(bot, chat_id, text, reply_to=message.message_id,
                               menu=ReplyKeyboardRemove(selective=True))

        items = self._api_client.get_resources()
        items = list(filter(lambda x: not self._is_filtered_for(chat_id, x.identifier), items))

        # then fuzzy match to "identifier"
        await self._response_handler.await_user_selection(
            update, context, identifier, choices=items, key=lambda x: x.identifier,
            callback=execute
        )

    @COMMAND_TIME_APPROVE.time()
    @command(name=COMMAND_APPROVE,
             description="Approve a pending item",
             arguments=[
                 Argument(name=["identifier", "i"], description="Approval identifier or id",
                          example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             error_handler=CustomErrorHandler(),
             permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS)
    async def _approve_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                identifier: str, voter: str or None) -> None:
        """
        Approve a pending item
        """
        chat_id = update.effective_chat.id

        if voter is None:
            voter = update.effective_user.full_name

        async def execute(update: Update, context: ContextTypes.DEFAULT_TYPE, item: Approval, data: dict):
            bot = context.bot
            message = update.effective_message
            chat_id = update.effective_chat.id

            self._api_client.approve(item.id, item.identifier, voter)
            text = f"Approved {item.identifier}"
            await send_message(bot, chat_id, text, reply_to=message.message_id,
                               menu=ReplyKeyboardRemove(selective=True))

        items = self._api_client.get_approvals(rejected=False, archived=False)
        items = list(filter(lambda x: not self._is_filtered_for(chat_id, x.identifier), items))

        # compare to the "id" first
        exact_matches = list(filter(lambda x: x.id == identifier, items))
        if len(exact_matches) > 0:
            await execute(update, context, exact_matches[0], {})
            return

        # then fuzzy match to "identifier"
        await self._response_handler.await_user_selection(
            update, context, identifier, choices=items, key=lambda x: x.identifier,
            callback=execute,
        )

    @COMMAND_TIME_REJECT.time()
    @command(name=COMMAND_REJECT,
             description="Reject a pending item",
             arguments=[
                 Argument(name=["identifier", "i"], description="Approval identifier or id",
                          example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             error_handler=CustomErrorHandler(),
             permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS)
    async def _reject_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                               identifier: str, voter: str or None) -> None:
        """
        Reject a pending item
        """
        chat_id = update.effective_chat.id
        if voter is None:
            voter = update.effective_user.full_name
        if not voter:
            voter = update.effective_user.name

        async def execute(update: Update, context: ContextTypes.DEFAULT_TYPE, item: Approval, data: dict):
            bot = context.bot
            message = update.effective_message
            chat_id = update.effective_chat.id

            self._api_client.reject(item.id, item.identifier, voter)
            text = f"Rejected {item.identifier}"
            await send_message(bot, chat_id, text, reply_to=message.message_id,
                               menu=ReplyKeyboardRemove(selective=True))

        items = self._api_client.get_approvals(rejected=False, archived=False)
        items = list(filter(lambda x: not self._is_filtered_for(chat_id, x.identifier), items))

        # compare to the "id" first
        exact_matches = list(filter(lambda x: x.id == identifier, items))
        if len(exact_matches) > 0:
            await execute(update, context, exact_matches[0], {})
            return

        # then fuzzy match to "identifier"
        await self._response_handler.await_user_selection(
            update, context, identifier, choices=items, key=lambda x: x.identifier,
            callback=execute,
        )

    @COMMAND_TIME_DELETE.time()
    @command(name=COMMAND_DELETE,
             description="Delete an approval item",
             arguments=[
                 Argument(name=["identifier", "i"], description="Approval identifier or id",
                          example="default/myimage:1.5.5"),
                 Argument(name=["voter", "v"], description="Name of voter", example="john", optional=True),
             ],
             error_handler=CustomErrorHandler(),
             permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS)
    async def _delete_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                               identifier: str, voter: str or None) -> None:
        """
        Delete an archived item
        """
        chat_id = update.effective_chat.id
        if voter is None:
            voter = update.effective_user.full_name

        async def execute(update: Update, context: ContextTypes.DEFAULT_TYPE, item: Approval, data: dict):
            bot = context.bot
            message = update.effective_message
            chat_id = update.effective_chat.id

            self._api_client.delete(item.id, item.identifier, voter)
            text = f"Deleted {item.identifier}"
            await send_message(bot, chat_id, text, reply_to=message.message_id,
                               menu=ReplyKeyboardRemove(selective=True))

        items = self._api_client.get_approvals()
        items = list(filter(lambda x: not self._is_filtered_for(chat_id, x.identifier), items))

        # compare to the "id" first
        exact_matches = list(filter(lambda x: x.id == identifier, items))
        if len(exact_matches) > 0:
            await execute(update, context, exact_matches[0], {})
            return

        # then fuzzy match to "identifier"
        await self._response_handler.await_user_selection(
            update, context, identifier, choices=items, key=lambda x: x.identifier,
            callback=execute,
        )

    @COMMAND_TIME_STATS.time()
    @command(
        name=COMMAND_STATS,
        description="Print keel statistics.",
        error_handler=CustomErrorHandler(),
        permissions=CONFIG_ADMINS,
    )
    async def _stats_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        stats = self._api_client.get_stats()

        text = f"{stats}"
        await send_message(bot, chat_id, text, reply_to=message.message_id)

    async def on_notification(self, data: dict):
        """
        Handles incoming notifications (via Webhook)
        :param data: notification data
        """
        KEEL_NOTIFICATION_COUNTER.inc()

        identifier: str = data.get("identifier", "")
        if identifier == "":
            LOGGER.error("Received notification without identifier")
            return

        title = data.get("name", None)
        type = data.get("type", None)
        level = data.get("level", None)  # success/failure
        message = data.get("message", None)

        text = "\n".join([
            f"<b>{title}: {level}</b>",
            f"{identifier}",
            f"{type}",
            f"{message}",
        ])

        for chat_id in self._config.TELEGRAM_CHAT_IDS.value:

            if self._is_filtered_for(chat_id, identifier):
                continue

            await send_message(
                self.bot, chat_id,
                text, parse_mode="HTML",
                menu=None
            )

    async def on_new_pending_approval(self, item: Approval):
        """
        Handles new pending approvals by sending a message
        including an inline keyboard to all configured chat ids
        :param item: new pending approval
        """
        identifier = item.identifier
        text = approval_to_str(item)
        menu = self.create_approval_notification_menu(item)

        for chat_id in self._config.TELEGRAM_CHAT_IDS.value:

            if self._is_filtered_for(chat_id, identifier):
                LOGGER.debug(f"Skipping new pending approval for chat '{chat_id}' due to filters")
                continue

            LOGGER.debug(f"Sending pending approval message to '{chat_id}'")
            try:
                response = await send_message(
                    self.bot, chat_id,
                    text, parse_mode="HTML",
                    menu=menu
                )
                self._register_message(response.chat_id, response.message_id, item.id, item.identifier)
            except Exception as ex:
                LOGGER.exception(ex)

    @command(
        name=COMMAND_CONFIG,
        description="Print bot config.",
        error_handler=CustomErrorHandler(),
        permissions=CONFIGURED_CHAT_ID & CONFIG_ADMINS,
    )
    async def _config_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id
        text = self._config.print(TomlFormatter())
        await send_message(bot, chat_id, text, reply_to=message.message_id)

    @command(
        name=COMMAND_HELP,
        description="List commands supported by this bot.",
        error_handler=CustomErrorHandler(),
        permissions=CONFIG_ADMINS,
    )
    async def _help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        from telegram_click import generate_command_list
        text = await generate_command_list(update, context)
        await send_message(bot, chat_id, text,
                           parse_mode="MARKDOWN",
                           reply_to=message.message_id)

    @command(
        name=COMMAND_CHATID,
        description="Print chat ID.",
        error_handler=CustomErrorHandler(),
        permissions=CONFIG_ADMINS,
    )
    async def _chatid_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        text = update.message.chat_id
        await send_message(bot, chat_id, str(text), reply_to=message.message_id)

    @command(
        name=COMMAND_VERSION,
        description="Print bot version.",
        error_handler=CustomErrorHandler(),
        permissions=CONFIG_ADMINS,
    )
    async def _version_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot
        message = update.effective_message
        chat_id = update.effective_chat.id

        from keel_telegram_bot import __version__
        text = __version__
        await send_message(bot, chat_id, text, reply_to=message.message_id)

    async def _unknown_command_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles unknown commands send by a user
        :param update: the chat update object
        :param context: telegram context
        """
        message = update.effective_message
        username = "N/A"
        if update.effective_user is not None:
            username = update.effective_user.username

        user_is_admin = username in self._config.TELEGRAM_ADMIN_USERNAMES.value
        if user_is_admin:
            await self._help_callback(update, context)
            return

    async def _any_message_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Used to respond to response keyboard entry selections
        :param update: the chat update object
        :param context: telegram context
        """
        await self._response_handler.on_message(update, context)

    async def _inline_keyboard_click_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles inline keyboard button click callbacks
        :param update:
        :param context:
        """
        bot = context.bot
        from_user = update.callback_query.from_user

        message_text = update.effective_message.text
        query = update.callback_query
        query_id = query.id
        data = query.data

        if data == BUTTON_DATA_NOTHING:
            return

        try:
            matches = re.search(r"^Id: (.*)", message_text, flags=re.MULTILINE)
            approval_id = matches.group(1)
            matches = re.search(r"^Identifier: (.*)", message_text, flags=re.MULTILINE)
            approval_identifier = matches.group(1)

            if data == BUTTON_DATA_APPROVE:
                self._api_client.approve(approval_id, approval_identifier, from_user.full_name)
                answer_text = f"Approved '{approval_identifier}'"
                KEEL_APPROVAL_ACTION_COUNTER.labels(action="approve", identifier=approval_identifier).inc()
            elif data == BUTTON_DATA_REJECT:
                self._api_client.reject(approval_id, approval_identifier, from_user.full_name)
                answer_text = f"Rejected '{approval_identifier}'"
                KEEL_APPROVAL_ACTION_COUNTER.labels(action="reject", identifier=approval_identifier).inc()
            else:
                await bot.answer_callback_query(query_id, text="Unknown button")
                return

            await context.bot.answer_callback_query(query_id, text=answer_text)
            await self.update_messages()
        except HTTPError as e:
            LOGGER.error(e)
            await bot.answer_callback_query(query_id, text=f"{e.response.content.decode('utf-8')}")
        except Exception as e:
            LOGGER.error(e)
            await bot.answer_callback_query(query_id, text=f"Unknwon error")

    @staticmethod
    def _build_inline_keyboard(items: Dict[str, str]) -> InlineKeyboardMarkup:
        """
        Builds an inline button menu
        :param items: dictionary of "button text" -> "callback data" items
        :return: reply markup
        """
        keyboard = list(map(lambda x: InlineKeyboardButton(x[0], callback_data=x[1]), items.items()))
        return InlineKeyboardMarkup.from_column(keyboard)

    def create_approval_notification_menu(self, item: Approval) -> InlineKeyboardMarkup:
        keyboard_items = {}
        if item.archived:
            keyboard_items["Approved"] = BUTTON_DATA_NOTHING
        elif item.rejected:
            keyboard_items["Rejected"] = BUTTON_DATA_NOTHING
        else:
            if item.votesRequired > item.votesReceived:
                keyboard_items["Approve"] = BUTTON_DATA_APPROVE
                keyboard_items["Reject"] = BUTTON_DATA_REJECT

        return self._build_inline_keyboard(keyboard_items)

    def _register_message(self, chat_id: int, message_id: int, approval_id: str, approval_identifier: str):
        """
        Registers a telegram message, that corresponds with an approval notification.
        This is used to update this message. This is possible for approx. 48 hours, after
        which telegram prohibits modifications of the original message.
        :param chat_id: chat id
        :param message_id: message id
        :param approval_id: approval id
        :param approval_identifier: approval identifier
        """
        key = f"{approval_id}_{approval_identifier}"
        self._message_map.setdefault(key, {}).setdefault(chat_id, set()).add(message_id)

    async def update_messages(self):
        """
        Fetch approvals and update existing approval messages accordingly
        """
        approvals = self._api_client.get_approvals()

        for approval in approvals:

            if approval.archived or approval.rejected:
                # TODO: avoid updating archived (accepted) or rejected items
                # to reduce the number of API calls to the Telegram API
                pass
                #continue

            approval_id = approval.id
            approval_identifier = approval.identifier
            key = f"{approval_id}_{approval_identifier}"

            chats = self._message_map.get(key, {})
            failed_messages = set()
            for chat_id, message_ids in chats.items():

                if self._is_filtered_for(chat_id, approval_identifier):
                    continue

                for message_id in message_ids:
                    try:
                        approval_str = approval_to_str(approval)
                        menu = self.create_approval_notification_menu(approval)
                        await self.bot.edit_message_text(
                            approval_str,
                            chat_id=chat_id,
                            message_id=message_id,
                            parse_mode="HTML",
                            reply_markup=menu
                        )
                    except Exception as ex:
                        failed_messages.add(message_id)
                        LOGGER.exception(ex)

                for failure in failed_messages:
                    message_ids.remove(failure)

    def _is_filtered_for(self, chat_id: str or int, identifier: str) -> bool:
        chat_ids: List[str] = self._config.TELEGRAM_CHAT_IDS.value
        filter_config: List[Dict] = self._config.TELEGRAM_FILTERS.value

        chat_unknown = str(chat_id) not in chat_ids
        filter_doesnt_match = util._is_filtered_for(filter_config, str(chat_id), identifier)

        result = chat_unknown or filter_doesnt_match
        LOGGER.debug(
            f"Filtered identifier '{identifier}' for chat {chat_id} because: chat_unknown: {chat_unknown}, filter_doesnt_match: {filter_doesnt_match}, result: {result}")

        return result
