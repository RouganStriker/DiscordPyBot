import discord
import asyncio
import os


class BaseClient(discord.Client):
    def __str__(self):
        return '{0}'.format(self.__class__.__name__)

    @asyncio.coroutine
    def on_ready(self):
        print('{0}: Logged in as'.format(self))
        print(self.user.name)
        print(self.user.id)
        print('------')

    @asyncio.coroutine
    def on_message(self, message):
        self.handle_message(message)

    @asyncio.coroutine
    def on_message_delete(self, message):
        self.handle_message_delete(message)

    def handle_message(self, message):
        print('{0}: Received message - {1}'.format(message, self))

    def handle_message_delete(self, message):
        pass


class ListenerClient(BaseClient):
    def __init__(self, relay_client=None, *args, **kwargs):
        self.relay_client = relay_client
        super(ListenerClient, self).__init__(*args, **kwargs)


class RelayClient(BaseClient):
    def handle_message(self, message):
        pass


#
#
# @listenerClient.event
# async def on_message(message):
#     if message.content.startswith('!test'):
#         counter = 0
#         tmp = await listenerClient.send_message(message.channel, 'Calculating messages...')
#         async for log in listenerClient.logs_from(message.channel, limit=100):
#             if log.author == message.author:
#                 counter += 1
#
#         await listenerClient.edit_message(tmp, 'You have {} messages.'.format(counter))
#     elif message.content.startswith('!sleep'):
#         await asyncio.sleep(5)
#         await listenerClient.send_message(message.channel, 'Done sleeping')
#
#
# @relayClient.event
# async def on_ready():
#     print('Logged in as')
#     print(relayClient.user.name)
#     print(relayClient.user.id)
#     print('------')


relayClient = RelayClient()
listenerClient = ListenerClient(relayClient)

if os.environ.get('RELAY_DEV_MODE', False):
    relayClient.run(os.environ['DISCORD_DEV_BOT_TOKEN'])
else:
    relayClient.run(os.environ['DISCORD_BOT_TOKEN'])

listenerClient.run(os.environ['BDO_BOSS_TRACKER_LISTENER_TOKEN'])
