"""ZYRA automatic promotion manager.

Group delivery is enabled for groups the connected account is already in when
`.promo on` is used, and new groups are auto-enrolled when they become active.
Each group receives at most one promo per configured interval (default 24h).
Private chats are strictly opt-in via `.promo subscribe`.
"""
import asyncio
import html
import os
import re
import time
from urllib.parse import urlparse

from telethon import events
import db as database

DEFAULT_ON = os.environ.get("AUTO_PROMO", "false").lower() == "true"
DEFAULT_LINK = os.environ.get("PROMO_CHANNEL", "").strip()
OWNER_LINK = os.environ.get("PROMO_OWNER_LINK", "https://t.me/coderxsem").strip()
try:
    DEFAULT_INTERVAL = max(3600, min(30 * 86400, int(os.environ.get("PROMO_INTERVAL_SECONDS", "86400"))))
except (TypeError, ValueError):
    DEFAULT_INTERVAL = 86400
TEMPLATES = [
    "𓆩 🖤 𓆪 <b>𝐙𝐘𝐑𝐀 𝐖𝐎𝐑𝐋𝐃</b>\n\n✨ ɴᴇᴡ ᴠɪʙᴇꜱ • ɴᴇᴡ ᴜᴘᴅᴀᴛᴇꜱ\n🦋 ᴊᴏɪɴ ᴏᴜʀ ᴄᴏᴍᴍᴜɴɪᴛʏ ᴀɴᴅ ꜱᴛᴀʏ ᴄᴏɴɴᴇᴄᴛᴇᴅ.",
    "💜 <b>𝐃𝐈𝐒𝐂𝐎𝐕𝐄𝐑 𝐙𝐘𝐑𝐀</b> 💜\n\n🎧 ᴄᴏᴍᴍᴜɴɪᴛʏ • ɴᴇᴡ ᴠɪʙᴇꜱ\n✨ ᴄʜᴇᴄᴋ ᴏᴜᴛ ᴏᴜʀ ᴜᴘᴅᴀᴛᴇꜱ ʙᴇʟᴏᴡ.",
    "𖤐 <b>𝐓𝐇𝐄 𝐙𝐘𝐑𝐀 𝐕𝐈𝐁𝐄</b> ⚡\n\n🖤 ᴄʟᴇᴀɴ ᴠɪʙᴇꜱ. ɢᴏᴏᴅ ᴘᴇᴏᴘʟᴇ. ɴᴇᴡ ᴜᴘᴅᴀᴛᴇꜱ.",
]


def valid_url(value):
    try:
        parsed = urlparse((value or "").strip())
        return parsed.scheme in ("https", "http") and bool(parsed.netloc)
    except Exception:
        return False


def parse_interval(value):
    match = re.fullmatch(r"\s*(\d{1,5})\s*(s|m|h|d)?\s*", value.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "h"
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return seconds if 3600 <= seconds <= 30 * 86400 else None


def setup(client):
    prefix = re.escape(client.prefix)
    uid = int(client.uid)
    configs = database.db.zyra_promo_config
    groups = database.db.zyra_promo_groups
    subscribers = database.db.zyra_promo_subscribers
    in_flight = set()

    async def get_config():
        return await configs.find_one({"uid": uid}) or {}

    async def promo_enabled():
        cfg = await get_config()
        return bool(cfg.get("enabled", DEFAULT_ON))

    async def status_message(e, title, body):
        await e.reply(
            "<blockquote>🎀 <b>" + title + "</b>\n━━━━━━━━━━━━━━━━━━\n" + body +
            "\n━━━━━━━━━━━━━━━━━━\n<i>✦ ᴢʏʀᴀ ᴀᴜᴛᴏ ᴘʀᴏᴍᴏ ✦</i></blockquote>",
            parse_mode="html",
        )
        try:
            await e.delete()
        except Exception:
            pass

    async def enroll_existing_groups():
        """Save current group destinations so promo starts without per-group setup."""
        count = 0
        try:
            async for dialog in client.iter_dialogs():
                if getattr(dialog, "is_group", False):
                    existing = await groups.find_one({"uid": uid, "chat_id": int(dialog.id)}) or {}
                    if existing.get("manual_disabled"):
                        continue
                    await groups.update_one(
                        {"uid": uid, "chat_id": int(dialog.id)},
                        {"$set": {"enabled": True, "title": getattr(dialog, "name", "")}},
                        upsert=True,
                    )
                    count += 1
        except Exception:
            pass
        return count

    async def promo_payload():
        cfg = await get_config()
        custom = (cfg.get("text") or "").strip()
        caption = "<b>" + html.escape(custom) + "</b>" if custom else __import__("random").choice(TEMPLATES)
        links = list(cfg.get("links") or [])
        fallback = cfg.get("link") or DEFAULT_LINK
        if valid_url(fallback) and not any(x.get("url") == fallback for x in links):
            links.append({"label": "𝐂𝐇𝐀𝐍𝐍𝐄𝐋", "url": fallback})
        if valid_url(OWNER_LINK) and not any(x.get("url") == OWNER_LINK for x in links):
            links.append({"label": "𝐎𝐖𝐍𝐄𝐑", "url": OWNER_LINK})
        link_line = "  ·  ".join(
            f'<a href="{html.escape(item["url"], quote=True)}">{html.escape((item.get("label") or "OPEN")[:32])}</a>'
            for item in links[:6] if valid_url(item.get("url"))
        )
        if link_line:
            caption += "\n\n" + link_line
        return cfg, caption

    async def send_promo(destination):
        cfg, caption = await promo_payload()
        image_chat, image_message = cfg.get("image_chat_id"), cfg.get("image_message_id")
        if image_chat and image_message:
            try:
                source = await client.get_messages(image_chat, ids=image_message)
                if source and source.media:
                    await client.send_file(destination, source, caption=caption, parse_mode="html")
                    return
            except Exception:
                pass
        await client.send_message(destination, caption, parse_mode="html", link_preview=False)

    async def maybe_send(destination, is_group=False):
        if not await promo_enabled():
            return False
        destination = int(destination)
        key = ("g" if is_group else "dm", destination)
        if key in in_flight:
            return False
        collection = groups if is_group else subscribers
        query = {"uid": uid, "chat_id": destination}
        record = await collection.find_one(query) or {}
        if not is_group and not record.get("enabled"):
            return False
        if is_group and record.get("enabled") is False:
            return False
        cfg = await get_config()
        interval = max(3600, int(cfg.get("interval_seconds", DEFAULT_INTERVAL)))
        remaining = interval - (time.time() - float(max(record.get("last_sent", 0), record.get("last_attempt", 0))))
        if remaining > 0:
            return False
        in_flight.add(key)
        try:
            await send_promo(destination)
            now = time.time()
            await collection.update_one(query, {"$set": {"enabled": True, "last_sent": now, "last_attempt": now}}, upsert=True)
            return True
        except Exception:
            await collection.update_one(query, {"$set": {"last_attempt": time.time()}}, upsert=True)
            return False
        finally:
            in_flight.discard(key)

    # Optional mention/reply promotion. It is off by default and still obeys the
    # per-group promo interval/cooldown enforced by maybe_send().
    @client.on(events.NewMessage(incoming=True))
    async def promo_on_mention_or_reply(event):
        if not event.is_group or not event.sender_id or event.sender_id == client.me_id:
            return
        try:
            sender = await event.get_sender()
            if not sender or getattr(sender, "bot", False):
                return
            cfg = await get_config()
            if not cfg.get("enabled", DEFAULT_ON) or not cfg.get("trigger_enabled", False):
                return
            addressed = bool(event.mentioned)
            if event.is_reply:
                replied = await event.get_reply_message()
                addressed = addressed or bool(replied and replied.sender_id == client.me_id)
            if addressed:
                await maybe_send(event.chat_id, is_group=True)
        except Exception:
            # Promotion automation must never interrupt ordinary chat handling.
            return

    @client.on(events.NewMessage(pattern=r"^" + prefix + r"promo(?:\s+(.*))?$", outgoing=True))
    async def promo_control(e):
        raw = (e.pattern_match.group(1) or "").strip()
        parts = raw.split(maxsplit=1)
        action = parts[0].lower() if parts else "status"
        value = parts[1].strip() if len(parts) > 1 else ""

        if action == "on":
            await configs.update_one({"uid": uid}, {"$set": {"enabled": True}}, upsert=True)
            count = await enroll_existing_groups()
            return await status_message(e, "AUTO-PROMO ON ✅", f"Promotion enabled. Existing groups enrolled: <b>{count}</b>. New groups auto-enrol when active. Group cooldown is one promo per configured interval. DM promo requires subscription.")
        if action == "off":
            await configs.update_one({"uid": uid}, {"$set": {"enabled": False}}, upsert=True)
            return await status_message(e, "AUTO-PROMO OFF 🛑", "All automatic promotions paused for this connected account.")
        if action == "status":
            cfg = await get_config()
            enabled_groups = await groups.count_documents({"uid": uid, "enabled": True})
            dm = await subscribers.count_documents({"uid": uid, "enabled": True})
            interval = int(cfg.get("interval_seconds", DEFAULT_INTERVAL))
            return await status_message(e, "PROMO STATUS", f"Account: <b>{'ON ✅' if cfg.get('enabled', DEFAULT_ON) else 'OFF 🛑'}</b>\nGroups enrolled: <b>{enabled_groups}</b>\nOpt-in DMs: <b>{dm}</b>\nInterval: <b>{interval // 3600}h</b>")
        if action == "trigger":
            if value.lower() not in ("on", "off", "status"):
                return await status_message(e, "MENTION PROMO", f"Use <code>{client.prefix}promo trigger on</code>, <code>{client.prefix}promo trigger off</code>, or <code>{client.prefix}promo trigger status</code>.")
            cfg = await get_config()
            if value.lower() == "status":
                enabled = bool(cfg.get("trigger_enabled", False))
                return await status_message(e, "MENTION PROMO STATUS", f"Mention/reply promotion: <b>{'ON ✅' if enabled else 'OFF 🛑'}</b>\nIt only runs in enrolled groups and respects the group promo interval.")
            enabled = value.lower() == "on"
            await configs.update_one({"uid": uid}, {"$set": {"trigger_enabled": enabled}}, upsert=True)
            return await status_message(e, "MENTION PROMO UPDATED", "Promo can now trigger when someone mentions you or replies to your message." if enabled else "Mention/reply-triggered promo is now off.")
        if action in ("set", "text"):
            if value.lower() == "clear":
                await configs.update_one({"uid": uid}, {"$unset": {"text": ""}}, upsert=True)
                return await status_message(e, "PROMO TEXT RESET", "Rotating ZYRA templates restored.")
            if not value:
                return await status_message(e, "TEXT NEEDED", f"Use <code>{client.prefix}promo set Your promotional message</code>")
            await configs.update_one({"uid": uid}, {"$set": {"text": value[:1500]}}, upsert=True)
            return await status_message(e, "PROMO TEXT SAVED", "Your custom promo message is saved.")
        if action == "link":
            if not valid_url(value):
                return await status_message(e, "LINK NEEDED", f"Use <code>{client.prefix}promo link https://t.me/yourchannel</code>")
            await configs.update_one({"uid": uid}, {"$set": {"link": value}}, upsert=True)
            return await status_message(e, "PROMO LINK SAVED", "Default promo link updated.")
        if action == "add":
            try:
                label, url = [x.strip() for x in value.split("|", 1)]
            except ValueError:
                return await status_message(e, "FORMAT NEEDED", f"Use <code>{client.prefix}promo add JOIN | https://t.me/group</code>")
            if not label or not valid_url(url):
                return await status_message(e, "INVALID LINK", "Please provide a button label and valid http(s) URL.")
            cfg = await get_config()
            links = list(cfg.get("links") or [])
            if any(item.get("url") == url for item in links):
                return await status_message(e, "DUPLICATE LINK", "This URL is already saved.")
            if len(links) >= 6:
                return await status_message(e, "LINK LIMIT", "Maximum 6 custom promo links.")
            links.append({"label": label[:32], "url": url})
            await configs.update_one({"uid": uid}, {"$set": {"links": links}}, upsert=True)
            return await status_message(e, "LINK ADDED", "Your clickable promo link has been saved.")
        if action == "remove":
            cfg = await get_config()
            links = list(cfg.get("links") or [])
            if value.isdigit() and 1 <= int(value) <= len(links):
                links.pop(int(value) - 1)
            else:
                links = [x for x in links if x.get("url") != value]
            await configs.update_one({"uid": uid}, {"$set": {"links": links}}, upsert=True)
            return await status_message(e, "LINK REMOVED", "Updated custom promo links.")
        if action == "list":
            cfg = await get_config()
            links = cfg.get("links") or []
            text = "\n".join(f"{i}. {html.escape(x.get('label','OPEN'))} — <code>{html.escape(x.get('url',''))}</code>" for i, x in enumerate(links, 1)) or "No custom buttons saved."
            return await status_message(e, "SAVED PROMOS", text)
        if action == "time":
            seconds = parse_interval(value)
            if seconds is None:
                return await status_message(e, "INVALID INTERVAL", f"Use <code>{client.prefix}promo time 12h</code>. Allowed: 1h–30d.")
            await configs.update_one({"uid": uid}, {"$set": {"interval_seconds": seconds}}, upsert=True)
            return await status_message(e, "INTERVAL SAVED", f"Automatic promo interval: <b>{seconds // 3600} hours</b>.")
        if action == "image":
            if not e.is_reply:
                return await status_message(e, "REPLY TO MEDIA", f"Reply to media with <code>{client.prefix}promo image</code>.")
            reply = await e.get_reply_message()
            if not reply or not reply.media:
                return await status_message(e, "NO MEDIA", "Reply directly to a message containing media.")
            await configs.update_one({"uid": uid}, {"$set": {"image_chat_id": int(e.chat_id), "image_message_id": int(reply.id)}}, upsert=True)
            return await status_message(e, "PROMO MEDIA SAVED", "Media will be used in future promos.")
        if action == "group":
            if not e.is_group or value.lower() not in ("on", "off"):
                return await status_message(e, "GROUP CONTROL", f"Use <code>{client.prefix}promo group on/off</code> inside a group.")
            enabled = value.lower() == "on"
            await groups.update_one(
                {"uid": uid, "chat_id": int(e.chat_id)},
                {"$set": {"enabled": enabled, "manual_disabled": not enabled}}, upsert=True,
            )
            return await status_message(e, "GROUP PROMO UPDATED", "Promotion enabled for this group." if enabled else "Promotion disabled for this group.")
        if action == "preview" or action == "test":
            try:
                await send_promo(e.chat_id)
                try:
                    await e.delete()
                except Exception:
                    pass
            except Exception as ex:
                await status_message(e, "PREVIEW FAILED", html.escape(str(ex)[:220]))
            return
        return await status_message(e, "PROMO COMMANDS", (
            f"<code>{client.prefix}promo on/off/status</code>\n"
            f"<code>{client.prefix}promo set Your message</code>\n"
            f"<code>{client.prefix}promo link https://t.me/channel</code>\n"
            f"<code>{client.prefix}promo add JOIN | https://t.me/group</code>\n"
            f"<code>{client.prefix}promo remove 1</code> · <code>{client.prefix}promo list</code>\n"
            f"<code>{client.prefix}promo time 12h</code>\n"
            f"<code>{client.prefix}promo trigger on/off/status</code> · promo on mention/reply\n"
            f"Reply to media: <code>{client.prefix}promo image</code> · <code>{client.prefix}promo test</code>\n"
            f"Group exception: <code>{client.prefix}promo group off</code>\n"
            f"DM opt-in: <code>{client.prefix}promo subscribe/unsubscribe</code>"
        ))

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def dm_subscription(e):
        text = (e.raw_text or "").strip().lower()
        if text == f"{client.prefix.lower()}promo subscribe":
            await subscribers.update_one({"uid": uid, "chat_id": int(e.chat_id)}, {"$set": {"enabled": True}}, upsert=True)
            await e.reply("💜 You’re subscribed to ZYRA updates. Send <code>" + html.escape(client.prefix) + "promo unsubscribe</code> anytime to stop.", parse_mode="html")
            return
        if text == f"{client.prefix.lower()}promo unsubscribe":
            await subscribers.update_one({"uid": uid, "chat_id": int(e.chat_id)}, {"$set": {"enabled": False}}, upsert=True)
            await e.reply("🛑 ZYRA promo updates are now off for this DM.")
            return
        if not text.startswith(client.prefix.lower()):
            await maybe_send(e.chat_id, is_group=False)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group))
    async def group_promo(e):
        if not await promo_enabled():
            return
        # New/previously unseen groups are enrolled automatically when active.
        existing = await groups.find_one({"uid": uid, "chat_id": int(e.chat_id)})
        if existing is None:
            chat = await e.get_chat()
            await groups.update_one(
                {"uid": uid, "chat_id": int(e.chat_id)},
                {"$setOnInsert": {"enabled": True, "manual_disabled": False, "title": getattr(chat, "title", "")}},
                upsert=True,
            )
        await maybe_send(e.chat_id, is_group=True)
