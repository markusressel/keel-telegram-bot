import unittest

from keel_telegram_bot import util


class BotTest(unittest.TestCase):

    def test_is_filtered_for_true(self):
        chat_id = "123456"
        identifier = "deployment/gameservers/satisfactory"

        filters = [
            {
                "chat_id": "123456",
                "identifier": ".*satisfactory.*"
            }
        ]

        result = util._is_filtered_for(filters, chat_id, identifier)

        self.assertTrue(result)

    def test_is_filtered_for_false(self):
        chat_id = "123456"
        identifier = "deployment/gameservers/satisfactory"

        filters = [
            {
                "chat_id": "123456",
                "identifier": ".*wiki.*"
            }
        ]

        result = util._is_filtered_for(filters, chat_id, identifier)

        self.assertFalse(result)

    def test_is_filtered_for_no_match(self):
        chat_id = "123456"
        identifier = "deployment/gameservers/satisfactory"

        filters = [
            {
                "chat_id": "654321",
                "identifier": ".*satisfactory.*"
            }
        ]

        result = util._is_filtered_for(filters, chat_id, identifier)

        self.assertFalse(result)
