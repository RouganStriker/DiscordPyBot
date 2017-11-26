import asyncio
import discord
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'config.json')


class BaseClient(discord.Client):
    def __str__(self):
        return '{0}'.format(self.__class__.__name__)

    @asyncio.coroutine
    def on_ready(self):
        print('{0}: Logged in as {1}'.format(self, self.user.name))


class ListenerClient(BaseClient):
    def __init__(self, relay_client=None, *args, **kwargs):
        super(ListenerClient, self).__init__(*args, **kwargs)

        self.relay_client = relay_client

        # Import config
        self.config = json.loads(CONFIG_FILE)

        # Ensure the IDs are strings
        bdo_config = self.config['BDOBossDiscord']
        id_fields = ['GuildID', 'TimerChannelID', 'NotificationChannelID', 'BotID']

        for field in id_fields:
            bdo_config[field] = str(bdo_config[field])

        bdo_config['StatusChannelIDs'] = [str(channel_id) for channel_id in  bdo_config['StatusChannelIDs']]

    @asyncio.coroutine
    def on_ready(self):
        super(ListenerClient, self).on_ready()

        bdo_config = self.config['BDOBossDiscord']
        self.tracker_guild = self.get_server(bdo_config['GuildID'])
        self.timer_channel = self.tracker_guild.get_channel(bdo_config['TimerChannelID'])

        assert(self.tracker_guild, "Invalid GuildID in config")
        assert(self.timer_channel, "Invalid TimerChannelID")
        assert(self.tracker_guild.get_channel(bdo_config['NotificationChannelID']), "Invalid NotificationChannelID")

        for channel_id in bdo_config['StatusChannelIDs']:
            assert(self.tracker_guild.get_channel(channel_id, "Invalid channel id {0} in StatusChannelIDs".format(channel_id)))

    @asyncio.coroutine
    def on_message(self, message):
        if message.author.id == self.user.id:
            # Ignore own messages
            return
        if message.server is None and message.channel.is_private and not message.author.bot:
            # This a PM from another User
            yield from self.send_message(message.channel, content=self.config['customStrings']['autoReply'])
            return
        if (message.server.id != self.config['BDOBossDiscord']['GuildID'] or
            message.author.id != self.config['BDOBossDiscord']['BotID']):
            # Exit early if the message is not from the boss discord or not send by the bot user
            return

        if message.channel.id == self.config['BDOBossDiscord']['TimerChannelID']:
            # Timer Channel Update
            self.relay_client.on_boss_timer_update(message)
        elif message.channel.id == self.config['BDOBossDiscord']['NotificationChannelID']:
            self.relay_client.on_boss_notification_update(message)
        elif message.channel.id in self.config['BDOBossDiscord']['StatusChannelIDs']:
            self.relay_client.on_boss_status_update(message)


class RelayClient(BaseClient):
    @asyncio.coroutine
    def on_message(self, message):
        print(self, ': received message', message.content)

    def on_boss_timer_update(self, timer_message):
        print("Relay received Boss Update Message {0}".format(timer_message.content))

    def on_boss_notification_update(self, notification_message):
        print("Relay received Boss Notification Message {0}".format(notification_message.content))

    def on_boss_status_update(self, status_message):
        print("Relay received Boss Update Message {0}".format(status_message.content))
