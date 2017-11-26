import asyncio
from collections import namedtuple
import os

from client import ListenerClient, RelayClient, RelayCommands


relayClient = RelayClient()
listenerClient = ListenerClient(relayClient)
relayClient.add_cog(RelayCommands(listenerClient, relayClient))

if os.environ.get('RELAY_DEV_MODE', 'False') == 'False':
    RELAY_TOKEN_VAR = 'DISCORD_DEV_BOT_TOKEN'
else:
    RELAY_TOKEN_VAR = 'DISCORD_BOT_TOKEN'

# First, we must attach an event signalling when the bot has been
# closed to the client itself so we know when to fully close the event loop.

Entry = namedtuple('Entry', 'client event token bot')
entries = [
    Entry(client=relayClient, event=asyncio.Event(), token=os.environ[RELAY_TOKEN_VAR], bot=True),
    Entry(client=listenerClient, event=asyncio.Event(), token=os.environ['BDO_BOSS_TRACKER_LISTENER_TOKEN'], bot=False)
]

# Then, we should login to all our clients and wrap the connect call
# so it knows when to do the actual full closure

loop = asyncio.get_event_loop()

async def login():
    for e in entries:
        await e.client.login(e.token, bot=e.bot)

async def wrapped_connect(entry):
    try:
        await entry.client.connect()
    except Exception as e:
        await entry.client.close()
        print('We got an exception: ', e.__class__.__name__, e)
        entry.event.set()

# actually check if we should close the event loop:
async def check_close():
    futures = [e.event.wait() for e in entries]
    await asyncio.wait(futures)

# here is when we actually login
loop.run_until_complete(login())

# now we connect to every client
for entry in entries:
    loop.create_task(wrapped_connect(entry))

# now we're waiting for all the clients to close
loop.run_forever()

# finally, we close the event loop
loop.close()
