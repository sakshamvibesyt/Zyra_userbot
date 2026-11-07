"""Configurable DM auto-reply (DM Trap) with persistent controls."""
import asyncio
import html
import os
import re
from telethon import events
import db as database

DEFAULT_TEXT = os.environ.get("DM_TEXT", "Hey {first_name}! Main abhi busy hoon, baad mein reply karunga. 🌙")
try:
    DEFAULT_COOL = max(60, min(86400, int(os.environ.get("DM_COOLDOWN", "3600"))))
except (TypeError, ValueError):
    DEFAULT_COOL = 3600


def parse_links(raw):
    result = []
    for item in raw.split(","):
        item = item.strip()
        match = re.match(r"^(.{1,64}?)\s*(?:\||:)\s*(https?://\S+)$", item, re.I)
        if match:
            result.append((match.group(1).strip(), match.group(2).strip()))
    return result


def render_text(template, sender):
    first = (getattr(sender, "first_name", None) or "there").strip()
    username = getattr(sender, "username", None) or ""
    user_id = str(getattr(sender, "id", ""))
    safe = html.escape(first)
    values = {
        "first_name": safe, "name": safe,
        "username": html.escape("@" + username if username else ""),
        "id": html.escape(user_id),
        "mention": f'<a href="tg://user?id={user_id}">{safe}</a>' if user_id else safe,
    }
    return re.sub(r"\{(first_name|name|username|mention|id)\}", lambda m: values[m.group(1)], template)


def setup(client):
    uid = int(client.uid)
    prefix = re.escape(client.prefix)
    configs = database.db.zyra_dmtrap_config
    last_replies = database.db.zyra_dmtrap_last

    async def get_config():
        return await configs.find_one({"uid": uid}) or {}

    async def send_status(e, title, body):
        await e.reply(f"<blockquote>🎀 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n{body}\n━━━━━━━━━━━━━━━━━━\n<i>✦ ZYRA DM TRAP ✦</i></blockquote>", parse_mode="html")
        try:
            await e.delete()
        except Exception:
            pass

    @client.on(events.NewMessage(pattern=r"^" + prefix + r"dmtrap(?:\s+(.*))?$", outgoing=True))
    async def dmtrap_control(e):
        raw = (e.pattern_match.group(1) or "").strip()
        parts = raw.split(maxsplit=1)
        action = parts[0].lower() if parts else "status"
        value = parts[1].strip() if len(parts) > 1 else ""
        cfg = await get_config()
        if action == "on":
            await configs.update_one({"uid": uid}, {"$set": {"enabled": True}}, upsert=True)
            return await send_status(e, "DM TRAP ON ✅", "Auto-reply enabled.")
        if action == "off":
            await configs.update_one({"uid": uid}, {"$set": {"enabled": False}}, upsert=True)
            return await send_status(e, "DM TRAP OFF 🛑", "Auto-reply paused.")
        if action == "set":
            if not value:
                return await send_status(e, "MESSAGE NEEDED", f"Use <code>{client.prefix}dmtrap set Your reply {{first_name}}</code>")
            await configs.update_one({"uid": uid}, {"$set": {"text": value[:3000]}}, upsert=True)
            return await send_status(e, "REPLY SAVED", "Your custom DM reply has been saved.")
        if action == "cooldown":
            try:
                seconds = int(value)
                if not 60 <= seconds <= 86400:
                    raise ValueError()
            except ValueError:
                return await send_status(e, "INVALID COOLDOWN", f"Use <code>{client.prefix}dmtrap cooldown 3600</code> (60–86400 seconds).")
            await configs.update_one({"uid": uid}, {"$set": {"cooldown": seconds}}, upsert=True)
            return await send_status(e, "COOLDOWN SAVED", f"Cooldown set to <b>{seconds} seconds</b>.")
        if action == "reset":
            await configs.update_one({"uid": uid}, {"$unset": {"text": "", "cooldown": ""}, "$set": {"enabled": True}}, upsert=True)
            return await send_status(e, "DM TRAP RESET", "Default message and cooldown restored; auto-reply is ON.")
        if action == "status":
            enabled = cfg.get("enabled", True)
            text = cfg.get("text", DEFAULT_TEXT)
            cooldown = int(cfg.get("cooldown", DEFAULT_COOL))
            return await send_status(e, "DM TRAP STATUS", f"Status: <b>{'ON ✅' if enabled else 'OFF 🛑'}</b>\nCooldown: <b>{cooldown}s</b>\nReply: <code>{html.escape(text[:250])}</code>")
        return await send_status(e, "DM TRAP COMMANDS", (
            f"<code>{client.prefix}dmtrap on/off/status</code>\n"
            f"<code>{client.prefix}dmtrap set Your reply {{first_name}}</code>\n"
            f"<code>{client.prefix}dmtrap cooldown 3600</code>\n"
            f"<code>{client.prefix}dmtrap reset</code>"
        ))

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def trap(e):
        if e.sender_id == client.me_id:
            return
        raw_text = (e.raw_text or "").strip()
        if raw_text.startswith(client.prefix):
            return
        sender = await e.get_sender()
        if not sender or getattr(sender, "bot", False):
            return
        cfg = await get_config()
        if cfg.get("enabled", True) is False:
            return
        cooldown = max(60, int(cfg.get("cooldown", DEFAULT_COOL)))
        now = __import__("time").time()
        previous = await last_replies.find_one({"uid": uid, "sender_id": int(e.sender_id)}) or {}
        if now - float(previous.get("last_sent", 0)) < cooldown:
            return
        await last_replies.update_one(
            {"uid": uid, "sender_id": int(e.sender_id)},
            {"$set": {"last_sent": now}}, upsert=True,
        )
        text = cfg.get("text", DEFAULT_TEXT)
        links = parse_links(os.environ.get("PROMO_LINKS", ""))
        reply_text = render_text(text, sender)
        if links:
            reply_text += "\n\n" + "  ·  ".join(
                f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'
                for label, url in links
            )
        try:
            await e.reply(reply_text, parse_mode="html", link_preview=False)
        except Exception:
            try:
                await e.reply("Hey! Main abhi busy hoon, baad mein reply karunga. 🌙")
            except Exception:
                pass
