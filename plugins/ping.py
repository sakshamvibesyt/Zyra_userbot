import time
from telethon import events


def setup(client):
    p = client.prefix

    @client.on(events.NewMessage(pattern=r"^" + p + r"ping", outgoing=True))
    async def ping(e):
        t = time.perf_counter()
        m = await e.reply("<b>Pong</b>")
        await m.edit("<b>Pong</b> <code>%sms</code>" % round((time.perf_counter() - t) * 1000))
