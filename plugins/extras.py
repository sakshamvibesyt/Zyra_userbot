"""Safe utility, notes, AFK and auto-reply commands for Zyra Userbot."""
import ast
import asyncio
import html
import operator
import random
import re
import time

from telethon import events
import db as database

# In-memory AFK state; reset when the worker restarts.
_AFK = {}

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def _safe_calc(expr):
    if len(expr) > 100:
        raise ValueError("Expression too long")
    tree = ast.parse(expr, mode="eval")
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("Power too large")
            result = _OPS[type(node.op)](left, right)
            if abs(result) > 10**100:
                raise ValueError("Result too large")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        raise ValueError("Only basic arithmetic is allowed")
    return walk(tree)


def setup(client):
    p = re.escape(client.prefix)
    uid = client.uid
    notes = database.db.zyra_notes
    replies = database.db.zyra_replies
    filters = database.db.zyra_filters
    afk_settings = database.db.zyra_afk_settings
    afk_states = database.db.zyra_afk_states

    @client.on(events.NewMessage(pattern=r"^" + p + r"help$", outgoing=True))
    async def help_cmd(e):
        prefix = client.prefix
        await e.edit(
            "<b>╭━━━『 🎀 𝐙𝐘𝐑𝐀 𝐔𝐒𝐄𝐑𝐁𝐎𝐓 』━━━╮</b>\n"
            "<i>✦ Prime tools · Command guide ✦</i>\n"
            "<b>━━━━━━━━━━━━━━━━━━</b>\n\n"
            "<b>⚡ BASIC</b>\n"
            f"<code>{prefix}ping</code> · response speed\n"
            f"<code>{prefix}alive</code> · account status\n"
            f"<code>{prefix}help</code> · show this guide\n"
            f"<code>{prefix}id</code> · your/chat ID; reply to get target ID\n\n"
            "<b>👤 PROFILE CLONE / RESTORE</b>\n"
            f"Reply to a user's message: <code>{prefix}clone</code>\n"
            f"<code>{prefix}clone @username</code> · clone selected profile\n"
            f"<code>{prefix}reclone</code> or <code>{prefix}revert</code> · restore saved original profile\n"
            "<i>Use only with permission. Profile photo availability depends on Telegram.</i>\n\n"
            "<b>✧ TEXT & UTILITIES</b>\n"
            f"<code>{prefix}echo text</code> · repeat text\n"
            f"<code>{prefix}calc 2+2</code> · calculate\n"
            f"<code>{prefix}reverse text</code> · reverse text\n"
            f"<code>{prefix}clap text</code> · clap between words\n"
            f"<code>{prefix}emojify text</code> · add random emojis\n"
            f"<code>{prefix}spoiler text</code> · spoiler formatting\n"
            f"<code>{prefix}type text</code> · typewriter effect\n"
            f"<code>{prefix}tagjoin [group_id]</code> · import available group members (admin)\n"
            f"<code>{prefix}tagcount</code> / <code>{prefix}taglist</code> · saved member list\n"
            f"<code>{prefix}tagclear</code> · clear saved list with confirmation\n"
            f"<code>{prefix}tagall [message]</code> · admin-only, up to 150 recent members\n"
            f"<code>{prefix}tagcancel</code> · stop the active TagAll process\n"
            "<code>/setwelcome</code> · group welcome settings panel\n"
            f"<code>{prefix}addraid msg1 | msg2</code> · save message rotation\n"
            f"<code>{prefix}raid 5</code> · send up to 10 saved messages\n"
            f"<code>{prefix}clearraid</code> · clear saved messages\n\n"
            "<b>☾ AFK & AUTO-DROP</b>\n"
            f"<code>{prefix}afk [message]</code> · activate AFK with custom text\n"
            f"<code>{prefix}afkmsg message</code> · save default AFK message\n"
            f"<code>{prefix}afkmsg</code> · view saved message\n"
            f"<code>{prefix}unafk</code> · turn AFK off\n"
            f"<code>{prefix}promo on</code> · enable auto-drop\n"
            f"<code>{prefix}promo off</code> · pause auto-drop\n"
            f"<code>{prefix}promo status</code> · view status/channel\n\n"
            "<b>🗂 NOTES, AUTO-REPLY & FILTERS</b>\n"
            f"<code>{prefix}note name | text</code> · save note\n"
            f"<code>{prefix}getnote name</code> · read note\n"
            f"<code>{prefix}delnote name</code> · delete note\n"
            f"<code>{prefix}notes</code> · list notes\n"
            f"<code>{prefix}autoreply trigger | reply</code> · add auto-reply\n"
            f"<code>{prefix}delreply trigger</code> · remove auto-reply\n"
            f"<code>{prefix}replies</code> · list auto-replies\n"
            f"<code>{prefix}filter word | reply</code> · add current-chat filter\n"
            f"<code>{prefix}stop word</code> · remove filter\n"
            f"<code>{prefix}filters</code> · list current-chat filters\n\n"
            "<b>⚒ GROUP ADMIN</b>\n"
            f"<code>{prefix}adminhelp</code> · admin-only command guide\n\n"
            "<b>✦ AI</b>\n"
            f"<code>{prefix}ai question</code> · ask configured AI\n\n"
            "<b>━━━━━━━━━━━━━━━━━━</b>\n"
            "<i>Prefix follows your configuration. Promo needs PROMO_CHANNEL; AI needs a valid API key.\n"
            "Admin commands require Telegram permissions. Clone only with permission.</i>\n"
            "<b>╰━━━『 ᴍᴀᴅᴇ ᴡɪᴛʜ ᴢʏʀᴀ 💜 』━━━╯</b>"
        )


    # Per-chat saved rotation messages. Stored in MongoDB so they survive restarts.
    raid_store = database.db.zyra_raid_messages
    raid_running = set()

    @client.on(events.NewMessage(pattern=r"^" + p + r"addraid(?:\s+([\s\S]+))?$", outgoing=True))
    async def addraid(e):
        raw = (e.pattern_match.group(1) or "").strip()
        msgs = [part.strip() for part in raw.split("|") if part.strip()]
        if not msgs:
            return await e.edit("Usage: <code>%saddraid message 1 | message 2 | message 3</code>" % client.prefix)
        if len(msgs) > 20 or any(len(m) > 1000 for m in msgs):
            return await e.edit("Limit: maximum 20 messages; each message up to 1000 characters.")
        await raid_store.update_one({"uid": uid, "chat_id": e.chat_id}, {"$set": {"messages": msgs}}, upsert=True)
        await e.edit("✅ Saved <b>%d</b> rotation messages for this chat." % len(msgs))

    @client.on(events.NewMessage(pattern=r"^" + p + r"(?:clearraid|deltraid|delraid)$", outgoing=True))
    async def clearraid(e):
        await raid_store.delete_one({"uid": uid, "chat_id": e.chat_id})
        raid_running.discard(e.chat_id)
        await e.edit("🗑️ Saved rotation messages cleared for this chat.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"raid(?:\s+(\d+))?$", outgoing=True))
    async def raid(e):
        count = int(e.pattern_match.group(1) or 5)
        if count < 1 or count > 10:
            return await e.edit("Choose 1–10 messages per run to avoid flooding the chat.")
        doc = await raid_store.find_one({"uid": uid, "chat_id": e.chat_id})
        msgs = (doc or {}).get("messages", [])
        if not msgs:
            return await e.edit("No saved messages. Use <code>%saddraid msg1 | msg2</code> first." % client.prefix)
        if e.chat_id in raid_running:
            return await e.edit("A rotation is already running here. Use <code>%sstop</code> to stop it." % client.prefix)
        await e.delete()
        raid_running.add(e.chat_id)
        try:
            for i in range(count):
                if e.chat_id not in raid_running:
                    break
                await client.send_message(e.chat_id, msgs[i % len(msgs)])
                if i + 1 < count:
                    await asyncio.sleep(3)
        finally:
            raid_running.discard(e.chat_id)

    @client.on(events.NewMessage(pattern=r"^" + p + r"stop$", outgoing=True))
    async def stop_raid(e):
        if e.chat_id in raid_running:
            raid_running.discard(e.chat_id)
            await e.edit("⏹️ Message rotation stopped.")
        else:
            await e.edit("No active rotation in this chat.")

    # Kittu-style active-member tracking: keep each connected account and group separate.
    # Only lightweight public profile fields are stored; message contents are never saved.
    tagall_members = database.db.zyra_tagall_members
    tagall_running = {}
    TAGALL_MEMBER_LIMIT = 150
    TAGALL_DELAY_SECONDS = 2.5

    @client.on(events.NewMessage(incoming=True))
    async def track_tagall_active_member(event):
        if not event.is_group or not event.sender_id or event.sender_id == uid:
            return
        try:
            sender = await event.get_sender()
            if not sender or getattr(sender, "bot", False) or getattr(sender, "deleted", False):
                return
            member_info = {
                "id": sender.id,
                "name": getattr(sender, "first_name", None) or "Member",
                "username": getattr(sender, "username", None) or "",
                "last_seen": time.time(),
            }
            # Same bounded recent-member strategy as KittuBot: max 150 per group.
            await tagall_members.update_one(
                {"uid": uid, "chat_id": event.chat_id},
                {"$pull": {"active_members": {"id": sender.id}}},
                upsert=True,
            )
            await tagall_members.update_one(
                {"uid": uid, "chat_id": event.chat_id},
                {"$push": {"active_members": {"$each": [member_info], "$slice": -TAGALL_MEMBER_LIMIT}}},
            )
        except Exception:
            # Tracking is best-effort and must never interrupt normal message handling.
            return

    async def _tagall_is_group_admin(chat_id):
        try:
            permissions = await client.get_permissions(chat_id, uid)
            return bool(
                getattr(permissions, "is_admin", False)
                or getattr(permissions, "is_creator", False)
            )
        except Exception:
            return False

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagall(?:\s+([\s\S]+))?$", outgoing=True))
    async def tagall(e):
        if not e.is_group:
            return await e.edit("This command works only in groups.")
        if not await _tagall_is_group_admin(e.chat_id):
            return await e.edit("⛔ <b>Admin-only command.</b> Your connected account must be a group admin.")

        key = (uid, e.chat_id)
        if key in tagall_running:
            return await e.edit("A TagAll process is already running here. Use <code>%stagcancel</code> to stop it." % client.prefix)

        custom = (e.pattern_match.group(1) or "").strip()
        if not custom:
            custom = "👋 Everyone, please check this group announcement!"
        custom = custom[:700]

        member_doc = await tagall_members.find_one({"uid": uid, "chat_id": e.chat_id})
        members = (member_doc or {}).get("active_members", [])
        members = sorted(members, key=lambda item: item.get("last_seen", 0), reverse=True)[:TAGALL_MEMBER_LIMIT]
        if not members:
            return await e.edit(
                "No recently active members are recorded yet. Members will be added as they send messages; try TagAll later."
            )

        stop_event = asyncio.Event()
        tagall_running[key] = stop_event
        try:
            await e.delete()
            status = await client.send_message(
                e.chat_id,
                "📢 <b>TagAll started</b>\n"
                f"Tracking <b>{len(members)}</b> recently active members (maximum {TAGALL_MEMBER_LIMIT}).\n"
                f"One quoted message per member. Use <code>{html.escape(client.prefix)}tagcancel</code> to stop.",
                parse_mode="html",
            )
            sent = 0
            failed = 0
            for index, member in enumerate(members, start=1):
                if stop_event.is_set():
                    break
                member_id = member.get("id")
                if not member_id:
                    failed += 1
                    continue
                display = html.escape((member.get("name") or "Member")[:64])
                mention = f'<a href="tg://user?id={int(member_id)}">{display}</a>'
                # Each outgoing message contains exactly one mention, in quote style.
                payload = f"<blockquote>{html.escape(custom)}</blockquote>\n{mention}"
                try:
                    await client.send_message(e.chat_id, payload, parse_mode="html", link_preview=False)
                    sent += 1
                except Exception as ex:
                    # Respect Telegram FloodWait and retry this single mention once.
                    wait_seconds = getattr(ex, "seconds", None)
                    if wait_seconds is not None:
                        try:
                            await status.edit(
                                f"⏳ <b>Telegram rate limit</b>\nWaiting {int(wait_seconds)} seconds before continuing…",
                                parse_mode="html",
                            )
                            await asyncio.sleep(max(1, int(wait_seconds) + 1))
                            if stop_event.is_set():
                                break
                            await client.send_message(e.chat_id, payload, parse_mode="html", link_preview=False)
                            sent += 1
                        except Exception:
                            failed += 1
                    else:
                        failed += 1
                if index < len(members) and not stop_event.is_set():
                    await asyncio.sleep(TAGALL_DELAY_SECONDS)

            result = "🛑 <b>TagAll stopped.</b>" if stop_event.is_set() else "✅ <b>TagAll completed.</b>"
            await status.edit(
                f"{result}\n\n"
                f"• Mentions sent: <b>{sent}</b>\n"
                f"• Failed: <b>{failed}</b>\n"
                f"• Active-member list: <b>{len(members)}</b>",
                parse_mode="html",
            )
        finally:
            tagall_running.pop(key, None)

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagcancel$", outgoing=True))
    async def tagall_cancel(e):
        key = (uid, e.chat_id)
        running = tagall_running.get(key)
        if running:
            running.set()
            await e.edit("🛑 <b>TagAll cancellation requested.</b>")
        else:
            await e.edit("No TagAll process is running in this group.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"alive$", outgoing=True))
    async def alive(e):
        me = await client.get_me()
        await e.edit("<b>ZYRA is online</b>\nAccount: <code>%s</code>" % (me.first_name or me.id))

    @client.on(events.NewMessage(pattern=r"^" + p + r"echo\s+(.+)$", outgoing=True))
    async def echo(e):
        await e.edit(e.pattern_match.group(1), parse_mode=None)

    @client.on(events.NewMessage(pattern=r"^" + p + r"calc\s+(.+)$", outgoing=True))
    async def calc(e):
        try:
            result = _safe_calc(e.pattern_match.group(1).strip())
            await e.edit("<code>%s</code>" % html.escape(str(result)), parse_mode="html")
        except Exception as ex:
            await e.edit("Calculation error: <code>%s</code>" % str(ex)[:150])

    @client.on(events.NewMessage(pattern=r"^" + p + r"reverse\s+(.+)$", outgoing=True))
    async def reverse(e):
        await e.edit(e.pattern_match.group(1)[::-1], parse_mode=None)

    @client.on(events.NewMessage(pattern=r"^" + p + r"clap\s+(.+)$", outgoing=True))
    async def clap(e):
        await e.edit(" 👏 ".join(e.pattern_match.group(1).split()), parse_mode=None)

    @client.on(events.NewMessage(pattern=r"^" + p + r"emojify\s+(.+)$", outgoing=True))
    async def emojify(e):
        marks = ["✨", "🌸", "🖤", "⚡", "💫", "🌙", "🔥"]
        await e.edit(" ".join(w + random.choice(marks) for w in e.pattern_match.group(1).split()), parse_mode=None)

    @client.on(events.NewMessage(pattern=r"^" + p + r"spoiler\s+(.+)$", outgoing=True))
    async def spoiler(e):
        text = e.pattern_match.group(1)
        await e.edit("<tg-spoiler>%s</tg-spoiler>" % html.escape(text), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"type\s+(.+)$", outgoing=True))
    async def type_text(e):
        text = e.pattern_match.group(1)
        if len(text) > 300:
            return await e.edit("Text limit: 300 characters.")
        await e.edit("...", parse_mode=None)
        # Edit in small chunks to reduce Telegram edit-rate-limit errors.
        try:
            for i in range(2, len(text) + 1, 2):
                await e.edit(text[:i], parse_mode=None)
                await asyncio.sleep(0.10)
            if len(text) % 2:
                await e.edit(text)
        except Exception as ex:
            # Leave the last successfully rendered text instead of crashing the handler.
            try:
                await e.edit(text, parse_mode=None)
            except Exception:
                pass

    async def load_afk_state():
        """Load persistent AFK state so it survives a worker restart."""
        if uid in _AFK:
            return _AFK[uid]
        doc = await afk_states.find_one({"uid": uid})
        if doc and doc.get("active"):
            _AFK[uid] = {"message": doc.get("message", "I'm currently AFK."), "since": doc.get("since", time.time())}
        return _AFK.get(uid)

    @client.on(events.NewMessage(pattern=r"^" + p + r"afkmsg(?:\s+([\s\S]+))?$", outgoing=True))
    async def set_afk_message(e):
        message = e.pattern_match.group(1)
        if message is None:
            doc = await afk_settings.find_one({"uid": uid})
            current = doc.get("message") if doc else "I'm currently AFK. I'll reply when I'm back."
            return await e.edit("<b>✦ Saved AFK message</b>\n<pre>%s</pre>" % html.escape(current[:3500]))
        message = message.strip()
        if not message:
            return await e.edit("Usage: <code>%safkmsg your custom message</code>" % client.prefix)
        if len(message) > 3500:
            return await e.edit("AFK message is too long. Maximum: 3500 characters.")
        await afk_settings.update_one({"uid": uid}, {"$set": {"message": message}}, upsert=True)
        await e.edit("🎀 <b>Custom AFK message saved!</b>\nUse <code>%safk</code> to activate it." % client.prefix)

    @client.on(events.NewMessage(pattern=r"^" + p + r"afk(?:\s+([\s\S]+))?$", outgoing=True))
    async def afk(e):
        custom = e.pattern_match.group(1)
        if custom and custom.strip():
            message = custom.strip()
        else:
            doc = await afk_settings.find_one({"uid": uid})
            message = doc.get("message") if doc else "I'm currently AFK. I'll reply when I'm back."
        if len(message) > 3500:
            return await e.edit("AFK message is too long. Maximum: 3500 characters.")
        since = time.time()
        _AFK[uid] = {"message": message, "since": since}
        await afk_states.update_one({"uid": uid}, {"$set": {"active": True, "message": message, "since": since}}, upsert=True)
        await e.edit("🎀 <b>AFK enabled</b>\nYour custom message will be sent when someone messages you or mentions you.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"unafk$", outgoing=True))
    async def unafk(e):
        old = await load_afk_state()
        _AFK.pop(uid, None)
        await afk_states.update_one({"uid": uid}, {"$set": {"active": False}}, upsert=True)
        if old:
            await e.edit("✨ <b>Welcome back!</b> AFK was on for %d seconds." % int(time.time() - old["since"]))
        else:
            await e.edit("AFK was not enabled.")

    @client.on(events.NewMessage(outgoing=True))
    async def clear_afk_on_activity(e):
        # A normal outgoing message means the user is back. Don't clear AFK for commands.
        text = (e.raw_text or "").strip()
        if not text or text.startswith(client.prefix):
            return
        old = await load_afk_state()
        if old:
            _AFK.pop(uid, None)
            await afk_states.update_one({"uid": uid}, {"$set": {"active": False}}, upsert=True)

    @client.on(events.NewMessage(incoming=True))
    async def incoming(e):
        if not e.raw_text or getattr(e, "sender_id", None) == client.me_id:
            return
        afk_data = await load_afk_state()
        if afk_data and e.sender_id and (e.is_private or e.mentioned):
            try:
                # Escape user-configured text so any plain text, emoji, symbols, or newlines work safely.
                await e.reply(html.escape(afk_data["message"]))
            except Exception:
                pass
        text = e.raw_text.strip()
        # Personal auto-replies are exact, case-insensitive matches.
        doc = await replies.find_one({"uid": uid, "trigger": text.casefold()})
        if doc:
            try:
                await e.reply(doc["response"])
            except Exception:
                pass
        # Per-chat filters respond when a trigger appears in a message.
        async for f in filters.find({"uid": uid, "chat_id": e.chat_id}):
            if f["trigger"].casefold() in text.casefold():
                try:
                    await e.reply(f["response"])
                except Exception:
                    pass

    @client.on(events.NewMessage(pattern=r"^" + p + r"note\s+([^|]+?)\s*\|\s*(.+)$", outgoing=True))
    async def save_note(e):
        name, content = e.pattern_match.group(1).strip(), e.pattern_match.group(2).strip()
        await notes.update_one({"uid": uid, "name": name.casefold()}, {"$set": {"content": content, "name": name}}, upsert=True)
        await e.edit("Saved note <b>%s</b>." % name)

    @client.on(events.NewMessage(pattern=r"^" + p + r"getnote\s+(.+)$", outgoing=True))
    async def get_note(e):
        name = e.pattern_match.group(1).strip().casefold()
        doc = await notes.find_one({"uid": uid, "name": name})
        await e.edit(("<b>%s</b>\n%s" % (doc["name"], doc["content"])) if doc else "Note not found.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"delnote\s+(.+)$", outgoing=True))
    async def delete_note(e):
        name = e.pattern_match.group(1).strip().casefold()
        res = await notes.delete_one({"uid": uid, "name": name})
        await e.edit("Note deleted." if res.deleted_count else "Note not found.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"notes$", outgoing=True))
    async def list_notes(e):
        items = await notes.find({"uid": uid}).to_list(length=50)
        await e.edit("<b>Your notes</b>\n" + ("\n".join("• " + x["name"] for x in items) if items else "No notes saved."))

    @client.on(events.NewMessage(pattern=r"^" + p + r"autoreply\s+([^|]+?)\s*\|\s*(.+)$", outgoing=True))
    async def add_reply(e):
        trigger, response = e.pattern_match.group(1).strip(), e.pattern_match.group(2).strip()
        await replies.update_one({"uid": uid, "trigger": trigger.casefold()}, {"$set": {"trigger": trigger.casefold(), "response": response}}, upsert=True)
        await e.edit("Auto-reply saved for <code>%s</code>." % trigger)

    @client.on(events.NewMessage(pattern=r"^" + p + r"delreply\s+(.+)$", outgoing=True))
    async def del_reply(e):
        trigger = e.pattern_match.group(1).strip().casefold()
        res = await replies.delete_one({"uid": uid, "trigger": trigger})
        await e.edit("Auto-reply deleted." if res.deleted_count else "Trigger not found.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"replies$", outgoing=True))
    async def list_replies(e):
        items = await replies.find({"uid": uid}).to_list(length=50)
        await e.edit("<b>Auto-replies</b>\n" + ("\n".join("• " + x["trigger"] for x in items) if items else "No auto-replies."))

    @client.on(events.NewMessage(pattern=r"^" + p + r"filter\s+([^|]+?)\s*\|\s*(.+)$", outgoing=True))
    async def add_filter(e):
        trigger, response = e.pattern_match.group(1).strip(), e.pattern_match.group(2).strip()
        await filters.update_one({"uid": uid, "chat_id": e.chat_id, "trigger": trigger.casefold()}, {"$set": {"response": response}}, upsert=True)
        await e.edit("Filter saved in this chat for <code>%s</code>." % trigger)

    @client.on(events.NewMessage(pattern=r"^" + p + r"stop\s+(.+)$", outgoing=True))
    async def stop_filter(e):
        trigger = e.pattern_match.group(1).strip().casefold()
        res = await filters.delete_one({"uid": uid, "chat_id": e.chat_id, "trigger": trigger})
        await e.edit("Filter removed." if res.deleted_count else "Filter not found.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"filters$", outgoing=True))
    async def list_filters(e):
        items = await filters.find({"uid": uid, "chat_id": e.chat_id}).to_list(length=50)
        await e.edit("<b>Chat filters</b>\n" + ("\n".join("• " + x["trigger"] for x in items) if items else "No filters in this chat."))
