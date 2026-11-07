"""ZYRA Promotion Studio with opt-in destinations and user-account-safe URL links.

Telethon inline keyboards are bot-only, so this userbot publishes clickable HTML
links instead. Publish/cancel are controlled with commands rather than callbacks.
"""
import asyncio
import html
import logging
import re
from telethon import events
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserIsBlockedError

log = logging.getLogger(__name__)
URL_RE = re.compile(r"^\s*(.{1,64}?)\s*\|\s*(https?://\S+)\s*$", re.I)


def setup(client):
    prefix = re.escape(client.prefix)
    uid = int(client.uid)
    collection = __import__("db").db.zyra_broadcast_subscriptions
    sessions = {}
    pending = {}
    running = {"task": None, "stop": False}

    async def say(chat_id, text):
        return await client.send_message(chat_id, text, parse_mode="html", link_preview=False)

    async def send_status(e, text):
        try:
            await e.reply(text, parse_mode="html", link_preview=False)
        except Exception:
            pass

    def render_links(items):
        links = []
        for label, url in items[:8]:
            links.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>')
        return "\n\n" + "  ·  ".join(links) if links else ""

    async def begin(chat_id):
        sessions[int(chat_id)] = {"step": "media", "media_chat": None, "media_id": None, "caption": "", "links": []}
        await say(chat_id,
            "✦ <b>ZYRA PROMOTION STUDIO</b> ✦\n━━━━━━━━━━━━━━━━━━\n"
            "Let's create your post.\n\n<b>Step 1/3 · Media</b>\n"
            "Photo/video bhejo, ya media nahi chahiye to <code>/skip</code>.\n\n"
            "Cancel: <code>/cancel</code>")

    async def preview(chat_id, draft):
        pending[int(chat_id)] = draft
        source = None
        if draft.get("media_id"):
            source = await client.get_messages(draft["media_chat"], ids=draft["media_id"])
        caption = (draft.get("caption", "") or "") + render_links(draft.get("links", []))
        if source and source.media:
            await client.send_file(chat_id, source.media, caption=caption or None, parse_mode="html")
        else:
            await say(chat_id, caption or "<i>(No text)</i>")
        await say(chat_id,
            "<b>Preview ready.</b>\n\n"
            f"Publish: <code>{client.prefix}promotion publish</code>\n"
            f"Cancel: <code>{client.prefix}promotion cancel</code>\n"
            f"Status: <code>{client.prefix}promotion status</code>")

    async def deliver(draft, status_message):
        destinations = []
        async for doc in collection.find({"uid": uid}):
            destinations.append(doc)
        if not destinations:
            try:
                await status_message.edit("ℹ️ No opted-in destinations yet. Groups: <code>.broadcast here</code>; DM users: <code>.broadcast subscribe</code>.", parse_mode="html")
            except Exception:
                pass
            return
        source = None
        if draft.get("media_id"):
            source = await client.get_messages(draft["media_chat"], ids=draft["media_id"])
        caption = (draft.get("caption", "") or "") + render_links(draft.get("links", []))
        sent = failed = 0
        running["stop"] = False
        stopped = False
        try:
            for dest in destinations:
                if running["stop"]:
                    stopped = True
                    break
                target = int(dest["target_id"])
                try:
                    if source and source.media:
                        await client.send_file(target, source.media, caption=caption or None, parse_mode="html")
                    else:
                        await client.send_message(target, caption or "<i>(No text)</i>", parse_mode="html", link_preview=False)
                    sent += 1
                except FloodWaitError as ex:
                    await asyncio.sleep(ex.seconds + 1)
                    try:
                        if source and source.media:
                            await client.send_file(target, source.media, caption=caption or None, parse_mode="html")
                        else:
                            await client.send_message(target, caption or "<i>(No text)</i>", parse_mode="html", link_preview=False)
                        sent += 1
                    except Exception:
                        failed += 1
                except (ChatWriteForbiddenError, UserIsBlockedError):
                    failed += 1
                except Exception:
                    failed += 1
                    log.exception("promotion delivery failed uid=%s target=%s", uid, target)
                await asyncio.sleep(1.5)
        finally:
            running["task"] = None
            running["stop"] = False
            try:
                await status_message.edit(
                    "✦ <b>ZYRA PROMOTION REPORT</b> ✦\n━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Sent: <code>{sent}</code>\n❌ Failed: <code>{failed}</code>\n"
                    f"{'🛑 Stopped' if stopped else '🏁 Finished'}\n━━━━━━━━━━━━━━━━━━", parse_mode="html")
            except Exception:
                pass

    @client.on(events.NewMessage(pattern=r"(?is)^" + prefix + r"(?:promotion|broadcast)(?:\s+(.*))?$", outgoing=True))
    async def promotion_commands(e):
        raw = (e.raw_text or "").strip()
        match = re.match(r"(?is)^" + prefix + r"(promotion|broadcast)(?:\s+(.*))?$", raw)
        if not match:
            return
        root = match.group(1).lower()
        tail = (match.group(2) or "").strip()
        parts = tail.split(None, 1)
        action = parts[0].lower() if parts else ""

        if root == "broadcast" and action in ("here", "leave", "subscribe", "unsubscribe", "status", "stop", "help"):
            if action == "here":
                if not e.is_group:
                    return await send_status(e, "⚠️ <code>.broadcast here</code> group ke andar use karo.")
                await collection.update_one({"uid": uid, "kind": "group", "target_id": int(e.chat_id)}, {"$set": {"title": getattr(e.chat, "title", None) or str(e.chat_id)}}, upsert=True)
                return await send_status(e, "✅ This group has opted in to Zyra broadcasts. Remove with <code>.broadcast leave</code>.")
            if action == "leave":
                if not e.is_group:
                    return await send_status(e, "⚠️ Is command ko target group mein use karo.")
                await collection.delete_one({"uid": uid, "kind": "group", "target_id": int(e.chat_id)})
                return await send_status(e, "✅ This group has been removed from broadcast delivery.")
            if action == "subscribe":
                if not e.is_private:
                    return await send_status(e, "DM mein <code>.broadcast subscribe</code> bhejo.")
                await collection.update_one({"uid": uid, "kind": "dm", "target_id": int(e.sender_id)}, {"$set": {"title": "Telegram user"}}, upsert=True)
                return await send_status(e, "💜 Subscribed to Zyra updates. Stop with <code>.broadcast unsubscribe</code>.")
            if action == "unsubscribe":
                await collection.delete_one({"uid": uid, "kind": "dm", "target_id": int(e.sender_id)})
                return await send_status(e, "🛑 Unsubscribed from Zyra broadcast updates.")
            if action == "status":
                groups_count = await collection.count_documents({"uid": uid, "kind": "group"})
                dms = await collection.count_documents({"uid": uid, "kind": "dm"})
                active = bool(running["task"] and not running["task"].done())
                return await send_status(e, f"✦ <b>ZYRA BROADCAST STATUS</b> ✦\n👥 Opt-in groups: <code>{groups_count}</code>\n💌 Opt-in DMs: <code>{dms}</code>\n⚙️ Sending: <code>{'Yes' if active else 'No'}</code>")
            if action == "stop":
                if running["task"] and not running["task"].done():
                    running["stop"] = True
                    return await send_status(e, "🛑 Stop request sent.")
                return await send_status(e, "ℹ️ No promotion is running.")
            return await send_status(e, "✦ <b>ZYRA PROMOTION</b> ✦\n<code>.promotion</code> — create a post\n<code>.promotion publish</code> — publish draft\n<code>.broadcast status</code> — status\n<code>.broadcast here/leave</code> — group opt-in/out\n<code>.broadcast subscribe/unsubscribe</code> — DM opt-in/out\n<code>.broadcast stop</code> — stop sending")

        if action == "cancel":
            sessions.pop(int(e.chat_id), None)
            pending.pop(int(e.chat_id), None)
            return await send_status(e, "✖ Promotion draft cancelled.")
        if root == "promotion" and action == "publish":
            draft = pending.get(int(e.chat_id))
            if not draft:
                return await send_status(e, "⚠️ No ready draft. Use <code>.promotion</code> first.")
            if running["task"] and not running["task"].done():
                return await send_status(e, "⏳ Promotion already running. Use <code>.broadcast stop</code> if needed.")
            pending.pop(int(e.chat_id), None)
            status = await client.send_message(e.chat_id, "🚀 <b>Promotion started…</b>", parse_mode="html")
            running["task"] = asyncio.create_task(deliver(draft, status))
            return await send_status(e, "✅ Promotion publish command accepted.")
        if root == "promotion" and action in ("preview", "status"):
            if action == "status":
                active = bool(running["task"] and not running["task"].done())
                return await send_status(e, f"Promotion draft: <b>{'Ready to publish' if int(e.chat_id) in pending else 'None'}</b>\nSending: <b>{'Yes' if active else 'No'}</b>")
            draft = pending.get(int(e.chat_id))
            if not draft:
                return await send_status(e, "⚠️ No ready draft. Use <code>.promotion</code> first.")
            return await preview(e.chat_id, draft)
        if root == "promotion" or (root == "broadcast" and not action):
            if running["task"] and not running["task"].done():
                return await send_status(e, "⏳ A promotion is already being sent. Wait or use <code>.broadcast stop</code>.")
            return await begin(e.chat_id)

    @client.on(events.NewMessage(outgoing=True))
    async def promotion_wizard(e):
        chat_id = int(e.chat_id)
        draft = sessions.get(chat_id)
        if not draft:
            return
        raw = (e.raw_text or "").strip()
        if re.match(r"(?is)^" + prefix + r"(?:promotion|broadcast|cancel)(?:\s|$)", raw):
            return
        if raw.lower() == "/cancel":
            sessions.pop(chat_id, None)
            return await say(chat_id, "✖ Draft cancelled.")
        step = draft["step"]
        if step == "media":
            if raw.lower() == "/skip":
                draft["step"] = "caption"
            elif e.media:
                draft["media_chat"], draft["media_id"] = chat_id, int(e.id)
                draft["step"] = "caption"
            else:
                return await say(chat_id, "⚠️ Photo/video bhejo ya <code>/skip</code> likho.")
            return await say(chat_id, "<b>Step 2/3 · Message / Caption</b>\nText bhejo, ya blank caption ke liye <code>/skip</code>.")
        if step == "caption":
            draft["caption"] = "" if raw.lower() == "/skip" else raw
            draft["step"] = "links"
            return await say(chat_id, "<b>Step 3/3 · Clickable URL links</b>\nFormat: <code>OWNER | https://t.me/username</code>\nAdd links one by one. <code>/done</code> = finish, <code>/skip</code> = no links.")
        if step == "links":
            if raw.lower() in ("/skip", "/done"):
                sessions.pop(chat_id, None)
                return await preview(chat_id, draft)
            found = URL_RE.match(raw)
            if not found:
                return await say(chat_id, "⚠️ Format: <code>Link label | https://example.com</code>\nFinish with <code>/done</code> or <code>/skip</code>.")
            label, url = found.group(1).strip(), found.group(2).strip()
            if len(draft["links"]) >= 8:
                return await say(chat_id, "Maximum 8 links allowed. Send <code>/done</code> to preview.")
            draft["links"].append((label, url))
            return await say(chat_id, f"✅ Link added: <b>{html.escape(label)}</b>\nEk aur bhejo, ya <code>/done</code>.")

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def incoming_subscriptions(e):
        text = (e.raw_text or "").strip().lower()
        if text not in (f"{client.prefix.lower()}broadcast subscribe", f"{client.prefix.lower()}broadcast unsubscribe"):
            return
        sender = await e.get_sender()
        if not sender or getattr(sender, "bot", False) or sender.id == client.me_id:
            return
        if text.endswith("subscribe"):
            await collection.update_one({"uid": uid, "kind": "dm", "target_id": int(sender.id)}, {"$set": {"title": getattr(sender, "first_name", "Telegram user")}}, upsert=True)
            await e.reply("💜 Subscribed to Zyra updates. Send <code>.broadcast unsubscribe</code> anytime to stop.", parse_mode="html")
        else:
            await collection.delete_one({"uid": uid, "kind": "dm", "target_id": int(sender.id)})
            await e.reply("🛑 Unsubscribed from Zyra updates.")
