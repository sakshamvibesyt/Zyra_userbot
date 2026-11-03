import os
import asyncio
from telethon import events, Button

LINKS = [p.strip() for p in os.environ.get("PROMO_LINKS", "").split(",") if ":" in p]
TEXT = os.environ.get("DM_TEXT", "Hey {first_name}! Abhi thoda busy hoon, baad mein reply karta hoon. 🌙")
COOL = int(os.environ.get("DM_COOLDOWN", "3600"))


def _format_dm_text(template, sender):
    """Replace supported user placeholders without breaking other braces."""
    first_name = (getattr(sender, "first_name", None) or "there").strip()
    last_name = (getattr(sender, "last_name", None) or "").strip()
    username = getattr(sender, "username", None) or ""
    replacements = {
        "{first_name}": first_name,
        "{last_name}": last_name,
        "{username}": f"@{username}" if username else "",
        "{user_id}": str(getattr(sender, "id", "")),
    }
    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result


def setup(client):
    # Keep the existing behavior: the DM auto-reply is enabled only when
    # at least one PROMO_LINKS URL button is configured.
    if not LINKS:
        return

    btns = [[Button.url(*[x.strip() for x in p.split(":", 1)])] for p in LINKS]
    last = {}

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def trap(e):
        if e.sender_id == client.me_id:
            return

        try:
            sender = await e.get_sender()
        except Exception:
            sender = e.sender

        if sender and getattr(sender, "bot", False):
            return

        now = asyncio.get_event_loop().time()
        if now - last.get(e.sender_id, 0) < COOL:
            return
        last[e.sender_id] = now

        try:
            message = _format_dm_text(TEXT, sender) if sender else TEXT.replace("{first_name}", "there")
            await e.reply(message, buttons=btns)
        except Exception:
            pass
