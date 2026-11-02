import os, asyncio
from telethon import events, Button

LINKS = [p for p in os.environ.get("PROMO_LINKS", "").split(",") if ":" in p]
TEXT = os.environ.get("DM_TEXT", "Hey! Ye channels join kar lo 👇")
COOL = int(os.environ.get("DM_COOLDOWN", "3600"))


def setup(client):
    if not LINKS:
        return
    btns = [[Button.url(*[x.strip() for x in p.split(":", 1)])] for p in LINKS]
    last = {}

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def trap(e):
        if e.sender_id == client.me_id:
            return
        if e.sender and getattr(e.sender, "bot", False):
            return
        now = asyncio.get_event_loop().time()
        if now - last.get(e.sender_id, 0) < COOL:
            return
        last[e.sender_id] = now
        try:
            await e.reply(TEXT, buttons=btns)
        except Exception:
            pass
