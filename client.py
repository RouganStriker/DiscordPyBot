import asyncio
import discord
from discord.ext import commands
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import re

CONFIG_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'config.json')

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
handler = logging.handlers.TimedRotatingFileHandler(filename='discord.log', when='midnight', encoding='utf-8', backupCount=1)
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))

logger.addHandler(handler)

logger = logging.getLogger('relay')
logger.addHandler(logging.StreamHandler())
handler = TimedRotatingFileHandler(filename='bot.log', when='midnight', encoding='utf-8', backupCount=1)
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


class BaseClient(discord.Client):
    def __str__(self):
        return '{0}'.format(self.__class__.__name__)

    def __init__(self, *args, **kwargs):
        super(BaseClient, self).__init__(*args, **kwargs)

        # Import config
        with open(CONFIG_FILE) as f:
            self.config = json.load(f)

    @asyncio.coroutine
    async def on_ready(self):
        logger.info('{0}: Logged in as {1}'.format(self, self.user.name))


class ListenerClient(BaseClient):
    def __init__(self, relay_client=None, *args, **kwargs):
        super(ListenerClient, self).__init__(*args, **kwargs)

        self.relay_client = relay_client

        # Ensure the IDs are strings
        bdo_config = self.config['BDOBossDiscord']
        id_fields = ['GuildID', 'TimerChannelID', 'NotificationChannelID']

        for field in id_fields:
            bdo_config[field] = str(bdo_config[field])

        bdo_config['StatusChannelIDs'] = [str(channel_id) for channel_id in bdo_config['StatusChannelIDs']]
        bdo_config['BotIDs'] = [str(bot_id) for bot_id in bdo_config['BotIDs']]

    @asyncio.coroutine
    async def on_ready(self):
        await super(ListenerClient, self).on_ready()

        bdo_config = self.config['BDOBossDiscord']
        self.tracker_guild = self.get_server(bdo_config['GuildID'])
        self.timer_channel = self.tracker_guild.get_channel(bdo_config['TimerChannelID'])

        assert self.tracker_guild is not None, "Invalid GuildID in config"
        assert self.timer_channel is not None, "Invalid TimerChannelID"
        assert self.tracker_guild.get_channel(bdo_config['NotificationChannelID']) is not None, "Invalid NotificationChannelID"

        for channel_id in bdo_config['StatusChannelIDs']:
            assert self.tracker_guild.get_channel(channel_id) is not None, "Invalid channel id {0} in StatusChannelIDs".format(channel_id)

    @asyncio.coroutine
    async def on_message(self, message):
        if message.author.id == self.user.id:
            # Ignore own messages
            return
        if message.server is None and message.channel.is_private and not message.author.bot:
            # This a PM from another User
            await self.send_message(message.channel, content=self.config['customStrings']['autoReply'])
            return

        from_boss_discord = message.server.id == self.config['BDOBossDiscord']['GuildID']
        from_bot = message.author.bot

        if not from_boss_discord or not from_bot:
            # Exit early if the message is not from the boss discord or not send by the bot user
            return

        if message.channel.id == self.config['BDOBossDiscord']['TimerChannelID']:
            # Timer Channel Update
            await self.relay_client.on_boss_timer_update(message)
        elif message.channel.id == self.config['BDOBossDiscord']['NotificationChannelID']:
            await self.relay_client.on_boss_notification_update(message)
        elif message.channel.id in self.config['BDOBossDiscord']['StatusChannelIDs']:
            await self.relay_client.on_boss_status_update(message)

    @asyncio.coroutine
    async def on_member_join(self, member):
        await self.send_message(member, content=self.config['customStrings']['welcomeDirectMessage'])
        return

    @asyncio.coroutine
    async def on_member_update(self, before, after):
        trigger_roles = set(self.config['roleChangePlugin']['trigger_role_ids'])

        if {role.id for role in before.roles} & trigger_roles:
            # Don't re-trigger if the member had the roles already
            return

        if {role.id for role in after.roles} & trigger_roles:
            await self.send_message(after, content=self.config['roleChangePlugin']['message'])

        return


class DelayedMessage(object):
    lock = asyncio.Lock()
    is_sending = False
    content = None
    embeds = None

    def __init__(self, channels):
        self.channels = channels


class RelayClient(BaseClient, commands.Bot):
    def __init__(self, *args, **kwargs):
        description = "BDO Relay Bot"
        super(RelayClient, self).__init__(command_prefix='!', description=description, *args, **kwargs)

        self.boss_updates_cache = {name: None for name in self.config['BDOBossDiscord']['BossNameMapping'].keys()}

    @asyncio.coroutine
    async def on_ready(self):
        await super(RelayClient, self).on_ready()

        self.timer_channels = []
        self.status_channels = []
        notification_channels = []

        for channel in self.get_all_channels():
            if channel.is_private:
                continue
            if channel.name.lower() == self.config['timerChannelName'].lower():
                self.timer_channels.append(channel)
            if channel.name.lower() == self.config['notificationChannelName'].lower():
                notification_channels.append(channel)
            if channel.name.lower() == self.config['statusUpdateChannelName'].lower():
                self.status_channels.append(channel)

        logger.debug("Found {} timer channels".format(len(self.timer_channels)))
        logger.debug("Found {} status update channels".format(len(self.status_channels)))
        logger.debug("Found {} notification channels".format(len(notification_channels)))

        self.timer_message = DelayedMessage(self.timer_channels)
        self.status_messages = {boss: DelayedMessage(self.status_channels) for boss in self.config['BDOBossDiscord']['BossNameMapping'].values()}
        self.notification_message = DelayedMessage(notification_channels)

    @asyncio.coroutine
    async def queue_message(self, delayed_obj, new_message, clear_messages=None, update_existing=None):
        if delayed_obj.lock.locked():
            return

        with (await delayed_obj.lock):
            initiate_send = not delayed_obj.is_sending

            if initiate_send:
                delayed_obj.is_sending = True
            if new_message.content:
                delayed_obj.content = new_message.content
            if new_message.embeds:
                delayed_obj.embeds = new_message.embeds

            logger.debug("Relaying embeds and message < {0} > to all channels".format(new_message.content))
            for channel in delayed_obj.channels:
                existing_message = None

                if update_existing:
                    async for message in self.logs_from(channel):
                        if update_existing(message):
                            existing_message = message
                            logger.debug("Found existing message with id {}".format(message.id))
                            break
                if clear_messages:
                    logger.debug("Checking for messages to clear...")

                    def _delete_check(message):
                        return (not existing_message or message.id != existing_message.id) and clear_messages(message)

                    await self.purge_from(channel, check=_delete_check)

                if delayed_obj.embeds:
                    for embed in delayed_obj.embeds:
                        logger.debug("Relaying embed...")
                        if existing_message is None:
                            await self.send_message(channel, delayed_obj.content, embed=embed)
                        else:
                            await self.edit_message(existing_message, delayed_obj.content, embed=embed)
                        delayed_obj.content = None  # Send it with the first embed
                elif delayed_obj.content:
                    if existing_message is None:
                        await self.send_message(channel, delayed_obj.content)
                    else:
                        await self.edit_message(existing_message, delayed_obj.content)

            delayed_obj.content = None
            delayed_obj.embeds = None
            delayed_obj.is_sending = False

    @asyncio.coroutine
    async def on_boss_timer_update(self, timer_message):
        logger.debug("Relay received Boss Timer Message {0}".format(timer_message.content))

        # Recreate embeds
        embeds = []
        for embed in timer_message.embeds:
            embed = discord.Embed(description=embed.get('description'),
                                  color=embed.get('color'),
                                  title=embed.get('title'))
            embeds.append(embed)
        timer_message.embeds = embeds

        await self.queue_message(self.timer_message, timer_message, clear_messages=lambda message: True)

    @asyncio.coroutine
    async def on_boss_notification_update(self, notification_message):
        # We use boss status for notification and mentioning
        pass

    @asyncio.coroutine
    async def on_boss_status_update(self, status_message):
        logger.debug("Relay received Boss Update Message < {0} >".format(status_message.content))
        boss_name = None
        boss_mapping = self.config['BDOBossDiscord']['BossNameMapping']

        if status_message.attachments:
            boss_name = status_message.attachments[0].get('filename', '').split('.', maxsplit=1)[0].lower()
        if boss_name:
            # Update message content
            boss_name = boss_mapping[boss_name]
            existing_check = lambda message: re.search(boss_name, message.content, re.I)
            status_message.content = "@everyone {0} has spawned".format(boss_name)
            embeds = []
            for attachment in status_message.attachments:
                new_embed = discord.Embed()
                new_embed.set_image(url=attachment['url'])
                new_embed.set_author(name=status_message.author.display_name, icon_url=status_message.author.avatar_url)
                embeds.append(new_embed)
            status_message.embeds = embeds

            await self.queue_message(self.status_messages[boss_name], status_message, clear_messages=existing_check, update_existing=existing_check)
            return

        if status_message.embeds:
            for embed in status_message.embeds:
                boss_name = re.search(r'({})(?= all clear)'.format('|'.join(boss_mapping.keys())), embed['title'], re.I)

                if boss_name:
                    break

        if boss_name:
            # All clear message
            boss_name = boss_name.group(0).lower()
            existing_check = lambda message: re.search(boss_mapping[boss_name], message.content, re.I)

            for channel in self.status_channels:
                await self.purge_from(channel, check=existing_check)
                return

        logger.error("Unhandled message: id: {} content: {}".format(status_message.id, status_message.content))


class RelayCommands(object):
    def __init__(self, listener, bot):
        self.listener = listener
        self.bot = bot

        # Import config
        with open(CONFIG_FILE) as f:
            self.config = json.load(f)

    @commands.command(pass_context=True, no_pm=True)
    async def refreshBossTimer(self, ctx):
        await self.bot.say("Refreshed boss timer")

    @commands.command(pass_context=True, no_pm=True)
    async def clearBossCallouts(self, ctx):
        counter = 0
        callout_channel = discord.utils.get(ctx.message.server.channels, name=self.config['statusUpdateChannelName'])

        if not callout_channel:
            await self.bot.say("@{0} no {1} channel found".format(ctx.message.author.username, self.config['statusUpdateChannelName']))
            return

        loop = True
        while loop:
            loop = False

            async for message in self.bot.logs_from(callout_channel):
                if message.pinned:
                    continue

                await self.bot.delete_message(message)
                counter += 1
                loop = True

        logger.debug("Delete {0} messages".format(counter))

        await self.bot.say("Cleared boss call outs")
