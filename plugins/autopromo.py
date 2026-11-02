import os, random, asyncio
from telethon import events

ON = os.environ.get("AUTO_PROMO", "false").lower() == "true"
TEXT = os.environ.get("PROMO_TEXT", "🔗 {channel}")
CHANNEL = os.environ.get("PROMO_CHANNEL", "")
CHANCE = float(os.environ.get("PROMO_CHANCE", "0.05"))
COOL = int(os.environ.get("PROMO_COOLDOWN", "300"))


def setup(client):
    if not ON or not CHANNEL:
        return
    last = {}

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group))
    async def promo(e):
        now = asyncio.get_event_loop().time()
        if now - last.get(e.chat_id, 0) < COOL:
            return
        if random.random() > CHANCE:
            return
        last[e.chat_id] = now
        try:
            await e.reply(TEXT.format(channel=CHANNEL))
        except Exception:
            pass
