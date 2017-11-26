import asyncio
import discord
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'config.json')


class BaseClient(discord.Client):
    def __str__(self):
        return '{0}'.format(self.__class__.__name__)

    def __init__(self, *args, **kwargs):
        super(BaseClient, self).__init__(*args, **kwargs)

        # Import config
        with open(CONFIG_FILE) as f:
            self.config = json.load(f)

    @asyncio.coroutine
    def on_ready(self):
        print('{0}: Logged in as {1}'.format(self, self.user.name))


class ListenerClient(BaseClient):
    def __init__(self, relay_client=None, *args, **kwargs):
        super(ListenerClient, self).__init__(*args, **kwargs)

        self.relay_client = relay_client

        # Ensure the IDs are strings
        bdo_config = self.config['BDOBossDiscord']
        id_fields = ['GuildID', 'TimerChannelID', 'NotificationChannelID', 'BotID']

        for field in id_fields:
            bdo_config[field] = str(bdo_config[field])

        bdo_config['StatusChannelIDs'] = [str(channel_id) for channel_id in bdo_config['StatusChannelIDs']]

    @asyncio.coroutine
    def on_ready(self):
        bdo_config = self.config['BDOBossDiscord']
        self.tracker_guild = self.get_server(bdo_config['GuildID'])
        self.timer_channel = self.tracker_guild.get_channel(bdo_config['TimerChannelID'])

        assert self.tracker_guild is not None, "Invalid GuildID in config"
        assert self.timer_channel is not None, "Invalid TimerChannelID"
        assert self.tracker_guild.get_channel(bdo_config['NotificationChannelID']) is not None, "Invalid NotificationChannelID"

        for channel_id in bdo_config['StatusChannelIDs']:
            assert self.tracker_guild.get_channel(channel_id) is not None, "Invalid channel id {0} in StatusChannelIDs".format(channel_id)

        yield from super(ListenerClient, self).on_ready()

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


class MessageAggregator(object):
    lock = asyncio.Lock()
    content = None
    embed = None
    is_sending = False

    def __init__(self, client, channels):
        self.client = client
        self.channels = channels

    def send_message(self, content=None, embed=None):
        if content is None and embed is None:
            return

        with (yield from self.lock):
            initiate_send = not self.is_sending

            if initiate_send:
                self.is_sending = True
            if content:
                self.content = content
            if embed:
                self.embed = embed

        # Re-acquire lock to allow message to be updated
        if not initiate_send:
            return

        print("Initiating send")

        with (yield from self.lock):
            for channel in self.channels:
                yield from self.client.send_message(channel, content=self.content, embed=self.embed)

            self.content = None
            self.embed = None
            self.is_sending = False


class RelayClient(BaseClient):
    def __init__(self, *args, **kwargs):
        super(RelayClient, self).__init__(*args, **kwargs)

        timer_channels = []
        status_channels = []
        notification_channels = []

        for channel in self.get_all_channels():
            if channel.is_private:
                continue
            if channel.name.lower() == self.config['timerChannelName'].lower():
                timer_channels.append(channel)
            if channel.name.lower() == self.config['notificationChannelName'].lower():
                notification_channels.append(channel)
            if channel.name.lower() == self.config['statusUpdateChannelName'].lower():
                status_channels.append(channel)

        print("Found", len(timer_channels), "timer channels")
        print("Found", len(status_channels), "status update channels")
        print("Found", len(notification_channels), "notification channels")

        self.timer_message = MessageAggregator(self, timer_channels)
        self.status_message = MessageAggregator(self, status_channels)
        self.notification_message = MessageAggregator(self, notification_channels)

    @asyncio.coroutine
    def on_message(self, message):
        print(self, ': received message', message.content)

    def on_boss_timer_update(self, timer_message):
        print("Relay received Boss Timer Message {0}".format(timer_message.content))
        self.timer_message.send_message(timer_message.content, timer_message.embeds)

    def on_boss_notification_update(self, notification_message):
        print("Relay received Boss Notification Message {0}".format(notification_message.content))
        self.notification_message.send_message(notification_message.content, notification_message.embeds)

    def on_boss_status_update(self, status_message):
        print("Relay received Boss Update Message {0}".format(status_message.content))
        self.status_message.send_message(status_message.content, status_message.embeds)
