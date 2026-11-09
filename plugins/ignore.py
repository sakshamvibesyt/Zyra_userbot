"""Persistent ignore controls for users and chats."""
import html
import re
from telethon import events
import db as database


def setup(client):
    uid = int(client.uid)
    p = re.escape(client.prefix)
    users = database.db.zyra_ignored_users
    chats = database.db.zyra_ignored_chats

    async def target(e):
        if e.is_reply:
            msg = await e.get_reply_message()
            return (int(msg.sender_id), await msg.get_sender()) if msg and msg.sender_id else (None, None)
        raw = (e.pattern_match.group(1) or "").strip()
        if not raw:
            return None, None
        try:
            entity = await client.get_entity(int(raw) if raw.lstrip("-").isdigit() else raw)
            return int(entity.id), entity
        except Exception:
            return None, None

    @client.on(events.NewMessage(pattern=r"^" + p + r"ignore(?:\s+(.+))?$", outgoing=True))
    async def ignore(e):
        user_id, entity = await target(e)
        if not user_id:
            return await e.edit("Reply to a user's message or use <code>.ignore @username</code> / <code>.ignore user_id</code>.")
        if user_id == int(client.me_id):
            return await e.edit("You cannot ignore your own account.")
        await users.update_one({"uid": uid, "user_id": user_id}, {"$set": {
            "name": (getattr(entity, "first_name", None) or "User")[:80],
            "username": getattr(entity, "username", None) or ""
        }}, upsert=True)
        await e.edit("🚫 <b>User ignored.</b> Automatic replies will skip this user.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"unignore(?:\s+(.+))?$", outgoing=True))
    async def unignore(e):
        user_id, _ = await target(e)
        if not user_id:
            return await e.edit("Reply to a user or use <code>.unignore @username</code> / <code>.unignore user_id</code>.")
        res = await users.delete_one({"uid": uid, "user_id": user_id})
        await e.edit("✅ User unignored." if res.deleted_count else "User was not ignored.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"ignorechat$", outgoing=True))
    async def ignore_chat(e):
        if e.is_private:
            return await e.edit("Use this inside a group.")
        chat = await e.get_chat()
        await chats.update_one({"uid": uid, "chat_id": int(e.chat_id)}, {"$set": {
            "title": getattr(chat, "title", None) or str(e.chat_id)
        }}, upsert=True)
        await e.edit("🚫 This chat is now ignored by automatic listeners.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"unignorechat$", outgoing=True))
    async def unignore_chat(e):
        res = await chats.delete_one({"uid": uid, "chat_id": int(e.chat_id)})
        await e.edit("✅ Chat unignored." if res.deleted_count else "This chat was not ignored.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"ignored$", outgoing=True))
    async def list_ignored(e):
        us = await users.find({"uid": uid}).to_list(length=100)
        cs = await chats.find({"uid": uid}).to_list(length=100)
        ul = ["• %s · <code>%s</code>" % (html.escape(x.get("name", "User")), x["user_id"]) for x in us]
        cl = ["• %s · <code>%s</code>" % (html.escape(x.get("title", "Chat")), x["chat_id"]) for x in cs]
        await e.edit("<b>🚫 ZYRA IGNORE LIST</b>\n\n<b>Users</b>\n" + ("\n".join(ul) or "None") +
                     "\n\n<b>Chats</b>\n" + ("\n".join(cl) or "None"), parse_mode="html")
