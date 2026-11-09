"""Shared per-account ignore checks for all automatic listeners."""
import db as database

async def is_ignored(uid, sender_id=None, chat_id=None):
    uid = int(uid)
    if sender_id and await database.db.zyra_ignored_users.find_one({"uid": uid, "user_id": int(sender_id)}):
        return True
    if chat_id and await database.db.zyra_ignored_chats.find_one({"uid": uid, "chat_id": int(chat_id)}):
        return True
    return False
