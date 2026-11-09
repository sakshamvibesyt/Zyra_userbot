"""Privacy-conscious group activity logs for dashboard and optional logger group."""
import html
import os
import time
from telethon import events
import db as database
from guard import is_ignored


def setup(client):
    uid = int(client.uid)
    logs = database.db.zyra_activity_logs
    groups = database.db.zyra_seen_groups
    logger_group = int(os.environ.get("LOGGER_GROUP_ID", "0") or 0)
    last_sent = {}

    async def record(kind, chat_id=None, title="", detail="", sender_id=None, sender_name=""):
        await logs.insert_one({"uid": uid, "kind": kind, "chat_id": int(chat_id) if chat_id else None,
            "title": str(title)[:120], "detail": str(detail)[:180],
            "sender_id": int(sender_id) if sender_id else None,
            "sender_name": str(sender_name)[:80], "at": time.time()})
        stale = await logs.find({"uid": uid}).sort("at", -1).skip(250).to_list(length=100)
        if stale:
            await logs.delete_many({"_id": {"$in": [x["_id"] for x in stale]}})

    client.zyra_log = record

    @client.on(events.NewMessage(incoming=True))
    async def track_group_activity(e):
        if not e.is_group or not e.sender_id or e.sender_id == client.me_id:
            return
        if await is_ignored(uid, e.sender_id, e.chat_id):
            return
        try:
            chat = await e.get_chat()
            sender = await e.get_sender()
            title = getattr(chat, "title", None) or str(e.chat_id)
            name = getattr(sender, "first_name", None) or getattr(sender, "username", None) or "Member"
            now = time.time()
            await groups.update_one({"uid": uid, "chat_id": int(e.chat_id)},
                {"$set": {"title": title[:120], "last_seen": now}, "$inc": {"message_count": 1}}, upsert=True)
            # Store one activity summary per group per 15 minutes, not message contents.
            if now - last_sent.get(e.chat_id, 0) >= 900:
                last_sent[e.chat_id] = now
                await record("group_activity", e.chat_id, title, "Group activity window; message content not stored", e.sender_id, name)
                if logger_group:
                    try:
                        await client.send_message(logger_group,
                            "🧾 <b>ZYRA GROUP LOG</b>\nGroup: <b>%s</b>\nMember: <b>%s</b> · <code>%s</code>\n<i>Activity recorded; message content is not copied.</i>" %
                            (html.escape(title[:80]), html.escape(name[:60]), e.sender_id), parse_mode="html")
                    except Exception:
                        pass
        except Exception:
            return


    @client.on(events.ChatAction())
    async def track_membership(e):
        try:
            if await is_ignored(uid, None, e.chat_id):
                return
            joined = bool(getattr(e, "user_joined", False) or getattr(e, "user_added", False))
            left = bool(getattr(e, "user_left", False) or getattr(e, "user_kicked", False))
            if not joined and not left:
                return
            user = await e.get_user() if hasattr(e, "get_user") else None
            user_id = getattr(user, "id", None) or getattr(e, "user_id", None)
            name = getattr(user, "first_name", None) or "Member"
            chat = await e.get_chat()
            title = getattr(chat, "title", None) or str(e.chat_id)
            kind = "member_joined" if joined else "member_left"
            detail = ("Member joined" if joined else "Member left")
            await record(kind, e.chat_id, title, detail, user_id, name)
            await groups.update_one({"uid": uid, "chat_id": int(e.chat_id)},
                {"$set": {"title": title[:120], "last_seen": time.time()}}, upsert=True)
            if logger_group:
                await client.send_message(logger_group,
                    "👥 <b>ZYRA MEMBER LOG</b>\nGroup: <b>%s</b>\n%s: <b>%s</b>\nUser ID: <code>%s</code>" %
                    (html.escape(title[:80]), "Joined" if joined else "Left", html.escape(name[:60]), user_id or "unknown"),
                    parse_mode="html")
        except Exception:
            return
