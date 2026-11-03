"""Opt-in, per-account Zyra promotion controls for Telethon userbot clients.

Commands: .promo on/off/status, .promo link URL, .promo text TEXT,
reply to media with .promo image, .promo group on/off, .promo preview.
DM recipients must explicitly send `.promo subscribe`; groups must be enabled
manually with `.promo group on`. Per-destination cooldown and random chance apply.
"""
import asyncio
import html
import os
import random
import re
from urllib.parse import urlparse

from telethon import Button, events
import db as database

DEFAULT_ON = os.environ.get("AUTO_PROMO", "false").lower() == "true"
DEFAULT_LINK = os.environ.get("PROMO_CHANNEL", "https://t.me/aboutsemx").strip()
OWNER_LINK = os.environ.get("PROMO_OWNER_LINK", "https://t.me/coderxsem").strip()
CHANCE = max(0.0, min(1.0, float(os.environ.get("PROMO_CHANCE", "0.05"))))
COOL = max(60, int(os.environ.get("PROMO_COOLDOWN", "1800")))

TEMPLATES = [
    "𓆩 🖤 𓆪 <b>𝐙𝐘𝐑𝐀 𝐖𝐎𝐑𝐋𝐃</b>\n\n✨ ɴᴇᴡ ᴠɪʙᴇꜱ • ɴᴇᴡ ᴜᴘᴅᴀᴛᴇꜱ\n🦋 ᴊᴏɪɴ ᴏᴜʀ ᴄᴏᴍᴍᴜɴɪᴛʏ ᴀɴᴅ ꜱᴛᴀʏ ᴄᴏɴɴᴇᴄᴛᴇᴅ.\n\n⚡ ᴋᴇᴇᴘ ɪᴛ ᴄʟᴀꜱꜱʏ. ᴋᴇᴇᴘ ɪᴛ ᴢʏʀᴀ.",
    "💜 <b>𝐃𝐈𝐒𝐂𝐎𝐕𝐄𝐑 𝐙𝐘𝐑𝐀</b> 💜\n\n🎧 ᴍᴜꜱɪᴄ • ᴄᴏᴍᴍᴜɴɪᴛʏ • ɴᴇᴡ ᴠɪʙᴇꜱ\n✨ ᴄʜᴇᴄᴋ ᴏᴜᴛ ᴏᴜʀ ᴜᴘᴅᴀᴛᴇꜱ ʙᴇʟᴏᴡ.",
    "𖤐 <b>𝐓𝐇𝐄 𝐙𝐘𝐑𝐀 𝐕𝐈𝐁𝐄</b> ⚡\n\n🖤 ᴄʟᴇᴀɴ ᴠɪʙᴇꜱ. ɢᴏᴏᴅ ᴘᴇᴏᴘʟᴇ. ɴᴇᴡ ᴜᴘᴅᴀᴛᴇꜱ.\n💫 ᴊᴏɪɴ ᴜꜱ ɪꜰ ʏᴏᴜ'ʀᴇ ɪɴᴛᴏ ɪᴛ.",
]


def valid_url(value):
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in ("https", "http") and bool(parsed.netloc)
    except Exception:
        return False


def setup(client):
    prefix = re.escape(client.prefix)
    uid = int(client.uid)
    configs = database.db.zyra_promo_config
    groups = database.db.zyra_promo_groups
    subscribers = database.db.zyra_promo_subscribers
    last_sent = {}

    async def get_config():
        return await configs.find_one({"uid": uid}) or {}

    async def is_enabled():
        cfg = await get_config()
        return bool(cfg.get("enabled", DEFAULT_ON))

    async def send_status(e, title, body):
        await e.reply(
            "<blockquote>🎀 <b>" + title + "</b>\n━━━━━━━━━━━━━━━━━━\n" + body +
            "\n━━━━━━━━━━━━━━━━━━\n<i>✦ ᴢʏʀᴀ ᴘʀᴏᴍᴏ ✦</i></blockquote>",
            parse_mode="html",
        )
        try:
            await e.delete()
        except Exception:
            pass

    async def promo_payload():
        cfg = await get_config()
        link = cfg.get("link") or DEFAULT_LINK
        custom = cfg.get("text", "").strip()
        if custom:
            caption = "<b>" + html.escape(custom) + "</b>\n\n✨ ᴄʜᴇᴄᴋ ᴜꜱ ᴏᴜᴛ ʙᴇʟᴏᴡ."
        else:
            caption = random.choice(TEMPLATES)
        buttons = []
        if valid_url(link):
            buttons.append(Button.url("𝐂𝐇𝐀𝐍𝐍𝐄𝐋", link))
        if valid_url(OWNER_LINK):
            buttons.append(Button.url("𝐎𝐖𝐍𝐄𝐑", OWNER_LINK))
        return cfg, caption, [buttons] if buttons else None

    async def send_promo(destination):
        cfg, caption, keyboard = await promo_payload()
        image_chat = cfg.get("image_chat_id")
        image_message = cfg.get("image_message_id")
        if image_chat and image_message:
            try:
                source = await client.get_messages(image_chat, ids=image_message)
                if source and source.media:
                    await client.send_file(destination, source, caption=caption, buttons=keyboard, parse_mode="html")
                    return
            except Exception:
                pass
        await client.send_message(destination, caption, buttons=keyboard, parse_mode="html", link_preview=False)

    async def maybe_send(destination, is_group=False):
        if not await is_enabled():
            return
        key = ("g" if is_group else "dm", int(destination))
        now = asyncio.get_running_loop().time()
        if now - last_sent.get(key, 0) < COOL or random.random() > CHANCE:
            return
        try:
            await send_promo(destination)
            last_sent[key] = now
        except Exception:
            return

    @client.on(events.NewMessage(pattern=r"^" + prefix + r"promo(?:\s+(.*))?$", outgoing=True))
    async def promo_control(e):
        raw = (e.pattern_match.group(1) or "").strip()
        parts = raw.split(maxsplit=1)
        action = parts[0].lower() if parts else "status"
        value = parts[1].strip() if len(parts) > 1 else ""

        if action == "on":
            await configs.update_one({"uid": uid}, {"$set": {"enabled": True}}, upsert=True)
            return await send_status(e, "AUTO-PROMO ON ✅", "Promotion enabled for this connected account. DM users must subscribe and each group must be enabled separately.")
        if action == "off":
            await configs.update_one({"uid": uid}, {"$set": {"enabled": False}}, upsert=True)
            return await send_status(e, "AUTO-PROMO OFF 🛑", "Promotion has been paused for this connected account.")
        if action == "status":
            cfg = await get_config()
            state = "ON ✅" if cfg.get("enabled", DEFAULT_ON) else "OFF 🛑"
            gc = await groups.count_documents({"uid": uid, "enabled": True})
            dm = await subscribers.count_documents({"uid": uid, "enabled": True})
            return await send_status(e, "PROMO STATUS", f"Account: <b>{state}</b>\nEnabled groups: <b>{gc}</b>\nOpt-in DMs: <b>{dm}</b>\nCooldown: <b>{COOL}s</b>")
        if action == "link":
            if not valid_url(value):
                return await send_status(e, "LINK NEEDED", "Use <code>.promo link https://t.me/yourchannel</code>")
            await configs.update_one({"uid": uid}, {"$set": {"link": value}}, upsert=True)
            return await send_status(e, "PROMO LINK SAVED", "Channel button link updated.")
        if action == "text":
            if value.lower() == "clear":
                await configs.update_one({"uid": uid}, {"$unset": {"text": ""}}, upsert=True)
                return await send_status(e, "TEXT RESET", "Rotating Zyra templates restored.")
            if not value:
                return await send_status(e, "TEXT NEEDED", "Use <code>.promo text Your promotion message</code>")
            await configs.update_one({"uid": uid}, {"$set": {"text": value}}, upsert=True)
            return await send_status(e, "PROMO TEXT SAVED", "Custom caption saved.")
        if action == "image":
            if not e.is_reply:
                return await send_status(e, "REPLY TO MEDIA", "Reply to an image, GIF, video or sticker with <code>.promo image</code>.")
            reply = await e.get_reply_message()
            if not reply or not reply.media:
                return await send_status(e, "NO MEDIA FOUND", "Reply directly to a message containing media.")
            await configs.update_one({"uid": uid}, {"$set": {"image_chat_id": int(e.chat_id), "image_message_id": int(reply.id)}}, upsert=True)
            return await send_status(e, "PROMO MEDIA SAVED", "This media will be used with future promotions.")
        if action == "group":
            if not e.is_group:
                return await send_status(e, "USE IN A GROUP", "Run <code>.promo group on</code> or <code>.promo group off</code> inside the target group.")
            if value.lower() not in ("on", "off"):
                return await send_status(e, "GROUP CONTROL", "Use <code>.promo group on</code> or <code>.promo group off</code>.")
            enabled = value.lower() == "on"
            await groups.update_one({"uid": uid, "chat_id": int(e.chat_id)}, {"$set": {"enabled": enabled}}, upsert=True)
            return await send_status(e, "GROUP PROMO " + ("ON ✅" if enabled else "OFF 🛑"), "This group has been " + ("enabled" if enabled else "disabled") + " for promotion.")
        if action == "preview":
            try:
                await send_promo(e.chat_id)
                try:
                    await e.delete()
                except Exception:
                    pass
            except Exception as ex:
                await send_status(e, "PREVIEW FAILED", html.escape(str(ex)[:250]))
            return
        return await send_status(e, "PROMO COMMANDS", (
            "<code>.promo on/off/status</code>\n"
            "<code>.promo link https://t.me/channel</code>\n"
            "<code>.promo text Your caption</code> (or <code>clear</code>)\n"
            "Reply to media: <code>.promo image</code>\n"
            "<code>.promo group on/off</code> (in a group)\n"
            "<code>.promo preview</code>\n"
            "DM users: <code>.promo subscribe</code> / <code>.promo unsubscribe</code>"
        ))

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def dm_subscription(e):
        text = (e.raw_text or "").strip().lower()
        if text == f"{client.prefix.lower()}promo subscribe":
            await subscribers.update_one({"uid": uid, "chat_id": int(e.chat_id)}, {"$set": {"enabled": True}}, upsert=True)
            await e.reply("💜 You’re subscribed to Zyra updates. Send <code>" + html.escape(client.prefix) + "promo unsubscribe</code> anytime to stop.", parse_mode="html")
            return
        if text == f"{client.prefix.lower()}promo unsubscribe":
            await subscribers.update_one({"uid": uid, "chat_id": int(e.chat_id)}, {"$set": {"enabled": False}}, upsert=True)
            await e.reply("🛑 Zyra promo updates are now off for this DM.")
            return
        if not text.startswith(client.prefix.lower()):
            doc = await subscribers.find_one({"uid": uid, "chat_id": int(e.chat_id), "enabled": True})
            if doc:
                await maybe_send(e.chat_id, is_group=False)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group))
    async def group_promo(e):
        doc = await groups.find_one({"uid": uid, "chat_id": int(e.chat_id), "enabled": True})
        if doc:
            await maybe_send(e.chat_id, is_group=True)
