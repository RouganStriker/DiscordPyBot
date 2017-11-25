import discord
import asyncio


class BaseClient(discord.Client):
    def __str__(self):
        return '{0}'.format(self.__class__.__name__)

    @asyncio.coroutine
    def on_ready(self):
        print('{0}: Logged in as {1}'.format(self, self.user.name))

    @asyncio.coroutine
    def on_message(self, message):
        self.handle_message(message)

    @asyncio.coroutine
    def on_message_delete(self, message):
        self.handle_message_delete(message)

    def handle_message(self, message):
        print('{0}: Received message - {1}'.format(self, message.__dict__))

    def handle_message_delete(self, message):
        pass


class ListenerClient(BaseClient):
    def __init__(self, relay_client=None, *args, **kwargs):
        self.relay_client = relay_client
        super(ListenerClient, self).__init__(*args, **kwargs)


class RelayClient(BaseClient):
    def handle_message(self, message):
        pass
