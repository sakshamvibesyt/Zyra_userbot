"""Opt-in broadcast for Zyra userbot.

Groups must explicitly opt in with .broadcast here. Private users opt in by
DMing .broadcast subscribe. A replied-to photo/media can be sent with a caption
and URL buttons using: .broadcast Caption text || Button label - https://example.com
Multiple URL buttons can be separated with semicolons.
"""
import asyncio
import logging
import re
from telethon import Button, events
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError

log = logging.getLogger(__name__)
URL_RE = re.compile(r"^\s*(.{1,64}?)\s*-\s*(https?://\S+)\s*$", re.I)


def _parse_caption_and_buttons(raw):
    """Parse caption and URL buttons from `caption || LABEL - URL; LABEL - URL`.

    Button definitions may be separated by semicolons or newlines. Also accepts
    hyphen/en-dash/em-dash between label and URL.
    """
    if "||" not in raw:
        return raw.strip() or None, None

    caption, raw_buttons = raw.split("||", 1)
    buttons = []
    # A semicolon is the primary separator; newline also works for copy/pasted commands.
    items = re.split(r"[;\n]+", raw_buttons)
    for item in items:
        item = item.strip()
        match = re.match(
            r"^(.{1,64}?)\s*[-–—]\s*(https?://\S+)\s*$",
            item,
            re.I,
        )
        if not match:
            continue
        label = match.group(1).strip()
        url = match.group(2).strip().rstrip(",")
        if label and url.startswith(("https://", "http://")):
            buttons.append(Button.url(label, url))

    # Telethon expects rows: [[button1, button2], [button3]].
    return caption.strip(), ([buttons] if buttons else None)


def _copy_url_buttons(message):
    """Rebuild URL buttons from a source message; callback buttons are not copied."""
    rows = []
    for row in (getattr(message, "buttons", None) or []):
        rebuilt = []
        for button in row:
            url = getattr(button, "url", None)
            label = getattr(button, "text", None)
            if url and label and str(url).startswith(("https://", "http://")):
                rebuilt.append(Button.url(str(label), str(url)))
        if rebuilt:
            rows.append(rebuilt)
    return rows or None


def setup(client):
    prefix = re.escape(client.prefix)
    uid = client.uid
    collection = __import__("db").db.zyra_broadcast_subscriptions
    running = {"task": None, "stop": False}

    async def reply(e, text):
        await e.reply(text, parse_mode="html")

    @client.on(events.NewMessage(pattern=r"(?s)^" + prefix + r"broadcast(?:\s+.*)?$", outgoing=True))
    async def broadcast_control(e):
        raw = (e.raw_text or "").strip()
        command = raw[len(client.prefix + "broadcast"):].strip()
        parts = command.split(None, 1)
        action = parts[0].lower() if parts else "send"
        remainder = parts[1] if len(parts) > 1 else ""

        if action == "here" and not remainder:
            if not e.is_group:
                return await reply(e, "⚠️ <b>.broadcast here</b> group ke andar use karo.")
            await collection.update_one(
                {"uid": uid, "kind": "group", "target_id": int(e.chat_id)},
                {"$set": {"title": (getattr(e.chat, "title", None) or str(e.chat_id))}}, upsert=True
            )
            return await reply(e, "📣 <b>Ye group broadcast list mein add ho gaya.</b>")
        if action == "leave" and not remainder:
            if not e.is_group:
                return await reply(e, "⚠️ <b>.broadcast leave</b> group ke andar use karo.")
            await collection.delete_one({"uid": uid, "kind": "group", "target_id": int(e.chat_id)})
            return await reply(e, "✅ Is group ko broadcast list se hata diya.")
        if action == "stop" and not remainder:
            if running["task"] and not running["task"].done():
                running["stop"] = True
                return await reply(e, "🛑 <b>Broadcast stop request mil gayi.</b>")
            return await reply(e, "ℹ️ Abhi koi broadcast nahi chal raha.")
        if action == "status" and not remainder:
            groups = await collection.count_documents({"uid": uid, "kind": "group"})
            dms = await collection.count_documents({"uid": uid, "kind": "dm"})
            active = bool(running["task"] and not running["task"].done())
            return await reply(e, "📊 <b>ZYRA BROADCAST STATUS</b>\n━━━━━━━━━━━━━━\n👥 Joined groups: <code>%s</code>\n💌 Opt-in DMs: <code>%s</code>\n⚙️ Running: <code>%s</code>\n━━━━━━━━━━━━━━" % (groups, dms, "Yes" if active else "No"))
        if action == "help" and not remainder:
            return await reply(e, "📣 <b>ZYRA BROADCAST</b>\n━━━━━━━━━━━━━━\n1. Group mein <code>.broadcast here</code> — group add\n2. Group mein <code>.broadcast leave</code> — group remove\n3. Kisi photo/media par reply karke <code>.broadcast Caption || Button - https://example.com</code>\n4. Sirf text bhejne ke liye message par reply karke <code>.broadcast</code>\n5. <code>.broadcast status</code> — counts\n6. <code>.broadcast stop</code> — stop request\n\n💌 DM users ko pehle <code>.broadcast subscribe</code> bhejna hoga; band karne ke liye <code>.broadcast unsubscribe</code>.\n<i>Broadcast sirf opted-in destinations par jaata hai.</i>")

        # A bare command or caption/options must reply to the image/media/text source.
        source = await e.get_reply_message()
        if not source:
            return await reply(e, "⚠️ Jis photo/message ko bhejna hai us par reply karo. Example: <code>.broadcast Caption || OWNER - https://t.me/username</code>")
        if running["task"] and not running["task"].done():
            return await reply(e, "⏳ Ek broadcast already chal raha hai. Finish hone ya <code>.broadcast stop</code> ka wait karo.")

        # If no custom caption/options are supplied, use the source caption/text and URL buttons.
        if command:
            caption, buttons = _parse_caption_and_buttons(command)
        else:
            caption, buttons = None, None
        if buttons is None:
            buttons = _copy_url_buttons(source)
        if caption is None:
            caption = source.message or ""
        preserve_entities = not command and bool(source.entities)

        destinations = []
        async for doc in collection.find({"uid": uid}):
            destinations.append(doc)
        if not destinations:
            return await reply(e, "ℹ️ Koi opted-in destination nahi hai. Group mein <code>.broadcast here</code> use karo ya users se DM mein <code>.broadcast subscribe</code> karwao.")

        running["stop"] = False
        status = await reply(e, "🚀 <b>Broadcast start ho gaya!</b>\n🖼️ Photo/media + caption\n🔘 URL buttons parsed: <code>%s</code>\n📬 Destinations: <code>%s</code>\n🛑 Stop: <code>.broadcast stop</code>" % (sum(len(row) for row in (buttons or [])), len(destinations)))

        async def deliver():
            sent, failed, stopped = 0, 0, False
            try:
                for dest in destinations:
                    if running["stop"]:
                        stopped = True
                        break
                    target = int(dest["target_id"])
                    try:
                        if source.media:
                            kwargs = {"caption": caption, "buttons": buttons}
                            if preserve_entities:
                                kwargs["formatting_entities"] = source.entities
                            await client.send_file(target, source.media, **kwargs)
                        else:
                            kwargs = {"buttons": buttons, "link_preview": False}
                            if preserve_entities:
                                kwargs["formatting_entities"] = source.entities
                            await client.send_message(target, caption, **kwargs)
                        sent += 1
                    except FloodWaitError as ex:
                        await asyncio.sleep(ex.seconds)
                        try:
                            if source.media:
                                await client.send_file(target, source.media, caption=caption, buttons=buttons)
                            else:
                                await client.send_message(target, caption, buttons=buttons, link_preview=False)
                            sent += 1
                        except Exception:
                            failed += 1
                    except (ChatWriteForbiddenError, UserIsBlockedError):
                        failed += 1
                    except Exception:
                        failed += 1
                        log.exception("broadcast delivery failed uid=%s target=%s", uid, target)
                    await asyncio.sleep(2)
            finally:
                running["task"] = None
                running["stop"] = False
                try:
                    await status.edit(
                        "📣 <b>BROADCAST REPORT</b>\n━━━━━━━━━━━━━━\n✅ Sent: <code>%s</code>\n❌ Failed: <code>%s</code>\n%s\n━━━━━━━━━━━━━━" % (
                            sent, failed, "🛑 Stopped by request" if stopped else "🏁 Completed"
                        ), parse_mode="html"
                    )
                except Exception:
                    pass

        running["task"] = asyncio.create_task(deliver())

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def dm_subscription(e):
        if not e.raw_text:
            return
        command = e.raw_text.strip().lower()
        if command == ".broadcast subscribe":
            sender = await e.get_sender()
            if not sender or getattr(sender, "bot", False) or sender.id == client.me_id:
                return
            await collection.update_one(
                {"uid": uid, "kind": "dm", "target_id": int(sender.id)},
                {"$set": {"title": getattr(sender, "first_name", "Telegram user")}}, upsert=True
            )
            await e.reply("✅ Broadcast updates ke liye subscribe ho gaye. Band karne ke liye <code>.broadcast unsubscribe</code> bhejo.", parse_mode="html")
        elif command == ".broadcast unsubscribe":
            sender = await e.get_sender()
            if not sender:
                return
            await collection.delete_one({"uid": uid, "kind": "dm", "target_id": int(sender.id)})
            await e.reply("✅ Broadcast updates se unsubscribe ho gaye.", parse_mode="html")
