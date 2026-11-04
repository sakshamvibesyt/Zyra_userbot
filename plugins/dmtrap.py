"""Personalized DM auto-reply using configured text and optional URL buttons.

Supported DM_TEXT placeholders: {first_name}, {name}, {username}, {mention}, {id}.
PROMO_LINKS format: Label|https://example.com,Another label|https://t.me/example
Only replies to people who message the connected account; cooldown limits repeats.
"""
import asyncio
import html
import os
import re
from telethon import events, Button

TEXT = os.environ.get("DM_TEXT", "Hey {first_name}! Main abhi busy hoon, baad mein reply karunga. 🌙")
COOL = max(60, int(os.environ.get("DM_COOLDOWN", "3600")))


def parse_links(raw):
    result = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        match = re.match(r"^(.{1,64}?)\s*(?:\||:)\s*(https?://\S+)$", item, re.I)
        if match:
            result.append((match.group(1).strip(), match.group(2).strip()))
    return result


def render_text(template, sender):
    first_name = (getattr(sender, "first_name", None) or "there").strip()
    username = getattr(sender, "username", None) or ""
    user_id = str(getattr(sender, "id", ""))
    safe_name = html.escape(first_name)
    values = {
        "first_name": safe_name,
        "name": safe_name,
        "username": html.escape("@" + username if username else ""),
        "id": html.escape(user_id),
        "mention": f'<a href="tg://user?id={user_id}">{safe_name}</a>' if user_id else safe_name,
    }
    # Replace only known placeholders; unknown braces remain untouched, so custom
    # text cannot crash the handler because of str.format() errors.
    return re.sub(r"\{(first_name|name|username|mention|id)\}", lambda m: values[m.group(1)], template)


def setup(client):
    links = parse_links(os.environ.get("PROMO_LINKS", ""))
    btns = [[Button.url(label, url)] for label, url in links] or None
    last = {}

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def trap(e):
        if e.sender_id == client.me_id:
            return
        sender = await e.get_sender()
        if not sender or getattr(sender, "bot", False):
            return
        now = asyncio.get_running_loop().time()
        if now - last.get(e.sender_id, 0) < COOL:
            return
        last[e.sender_id] = now
        try:
            await e.reply(render_text(TEXT, sender), buttons=btns, parse_mode="html", link_preview=False)
        except Exception:
            # A malformed custom template should not crash the whole userbot.
            try:
                await e.reply("Hey! Main abhi busy hoon, baad mein reply karunga. 🌙")
            except Exception:
                pass
