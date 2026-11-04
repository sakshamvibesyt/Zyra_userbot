"""Safe utility, notes, AFK and auto-reply commands for Zyra Userbot."""
import ast
import asyncio
import html
import operator
import random
import re
import time

from telethon import events, types
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


    # Group mention tools. Fetch all members exposed by Telegram, with a delay
    # between individual quote-style messages to reduce flood-wait errors.
    async def _collect_members(event, admins_only=False, limit=None):
        if not event.is_group:
            await event.edit("Ye command sirf group/supergroup mein use hoti hai.")
            return None
        members = []
        try:
            participant_filter = types.ChannelParticipantsAdmins if admins_only else None
            async for participant in client.iter_participants(event.chat_id, filter=participant_filter):
                if getattr(participant, "bot", False):
                    continue
                members.append(participant)
                if limit is not None and len(members) >= limit:
                    break
        except Exception as ex:
            await event.edit("Members fetch nahi ho paaya: <code>%s</code>" % html.escape(str(ex)[:180]))
            return None
        return members

    async def _mention_post(event, members, text, title):
        if not members:
            return await event.edit("Koi eligible member nahi mila.")
        # Send one quote-styled message per member, with a delay between posts.
        intro = html.escape((text or "Good morning").strip())
        await event.delete()
        sent = 0
        for member in members:
            raw_name = (getattr(member, "first_name", None) or getattr(member, "title", None) or "Member").strip()
            name = html.escape(raw_name)
            mention = '<a href="tg://user?id=%s">%s</a>' % (member.id, name)
            body = '<blockquote>%s\n%s</blockquote>' % (intro, mention)
            try:
                await client.send_message(event.chat_id, body, parse_mode="html")
                sent += 1
                await asyncio.sleep(1.0)
            except Exception:
                # Continue if a single member's message cannot be delivered.
                continue
        try:
            await client.send_message(
                event.chat_id,
                "<blockquote>✦ 𝐙𝐘𝐑𝐀 𝐓𝐀𝐆 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄 ✦\n"
                "╭━━━━━━━━━━━━━━╮\n"
                "  ♡ Members found: <b>%s</b>\n"
                "  ♡ Messages sent: <b>%s</b>\n"
                "╰━━━━━━━━━━━━━━╯\n"
                "Thanks for being here! 🎀</blockquote>" % (len(members), sent),
                parse_mode="html",
            )
        except Exception:
            pass

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagall(?:\s+([\s\S]+))?$", outgoing=True))
    async def tagall_cmd(e):
        text = e.pattern_match.group(1) or "Good morning"
        members = await _collect_members(e, admins_only=False)
        if members is not None:
            await _mention_post(e, members, text, "🔔 TAG ALL")

    @client.on(events.NewMessage(pattern=r"^" + p + r"(?:atag|atah)(?:\s+([\s\S]+))?$", outgoing=True))
    async def tag_admins_cmd(e):
        text = e.pattern_match.group(1) or "Good morning admins"
        members = await _collect_members(e, admins_only=True)
        if members is not None:
            await _mention_post(e, members, text, "⚙️ TAG ADMINS")

    @client.on(events.NewMessage(pattern=r"^" + p + r"onetag(?:\s+([\s\S]+))?$", outgoing=True))
    async def onetag_cmd(e):
        text = e.pattern_match.group(1) or "Hello"
        members = await _collect_members(e, admins_only=False)
        if members is not None:
            await _mention_post(e, members, text, "🏷 ONE-TAG")

    # Configurable, bounded group fun-message sequence. It deliberately does not
    # target/repeatedly mention a person. Maximum 3 messages and .stop cancels it.
    raid_messages = database.db.zyra_raid_messages
    _raid_tasks = {}

    @client.on(events.NewMessage(pattern=r"^" + p + r"addraid\s+([\s\S]+)$", outgoing=True))
    async def add_raid_message(e):
        message = (e.pattern_match.group(1) or "").strip()
        if not message:
            return await e.edit("Usage: <code>%saddraid Your friendly group message</code>" % html.escape(client.prefix))
        if len(message) > 500:
            return await e.edit("Message limit: 500 characters.")
        await raid_messages.update_one({"uid": uid}, {"$set": {"message": message}}, upsert=True)
        await e.edit("<b>✦ Raid message saved</b>\nUse <code>%sraid 3</code> in a group to send a short, non-targeted fun burst. Max 10 messages." % html.escape(client.prefix))

    @client.on(events.NewMessage(pattern=r"^" + p + r"raid(?:\s+(\d+))?$", outgoing=True))
    async def raid_message(e):
        if not e.is_group:
            return await e.edit("Ye command sirf group mein use karo.")
        count = int(e.pattern_match.group(1) or 1)
        count = max(1, min(count, 10))
        doc = await raid_messages.find_one({"uid": uid})
        message = (doc or {}).get("message")
        if not message:
            return await e.edit("Pehle message set karo: <code>%saddraid Your friendly group message</code>" % html.escape(client.prefix))
        key = e.chat_id
        existing = _raid_tasks.get(key)
        if existing and not existing.done():
            return await e.edit("Is group mein sequence already chal raha hai. Band karne ke liye <code>%sstop</code> bhejo." % html.escape(client.prefix))
        await e.delete()
        async def _run_sequence():
            try:
                for _ in range(count):
                    await client.send_message(e.chat_id, message)
                    await asyncio.sleep(1.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                _raid_tasks.pop(key, None)
        _raid_tasks[key] = asyncio.create_task(_run_sequence())

    @client.on(events.NewMessage(pattern=r"^" + p + r"stop$", outgoing=True))
    async def stop_raid(e):
        task = _raid_tasks.get(e.chat_id)
        if task and not task.done():
            task.cancel()
            await e.edit("🛑 Message sequence stopped.")
        else:
            await e.edit("Is group mein koi message sequence active nahi hai.")

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
            f"<code>{prefix}type text</code> · typewriter effect\n\n"
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
            f"<code>{prefix}tagall [text]</code> · send a separate quote-style message to all retrievable group members\n"
            f"<code>{prefix}atag [text]</code> / <code>{prefix}atah [text]</code> · mention admins\n"
            f"<code>{prefix}onetag [text]</code> · one-time compact mention\n"
            f"<code>{prefix}addraid message</code> · save a friendly group message\n"
            f"<code>{prefix}raid [1-3]</code> · short, non-targeted message sequence\n"
            f"<code>{prefix}stop</code> · stop the active sequence\n"
            f"<code>{prefix}adminhelp</code> · admin guide\n"
            f"Reply to target: <code>{prefix}ban</code>, <code>{prefix}unban</code>, <code>{prefix}mute</code>, <code>{prefix}unmute</code>, <code>{prefix}kick</code>, <code>{prefix}del</code>\n"
            f"<code>{prefix}pin</code> · pin replied message\n"
            f"<code>{prefix}unpin</code> · unpin latest message\n"
            f"<code>{prefix}purge 20</code> · delete recent messages (max 100)\n"
            f"<code>{prefix}admins</code> · list group admins\n\n"
            "<b>✦ AI</b>\n"
            f"<code>{prefix}ai question</code> · ask configured AI\n\n"
            "<b>━━━━━━━━━━━━━━━━━━</b>\n"
            "<i>Prefix follows your configuration. Promo needs PROMO_CHANNEL; AI needs a valid API key.\n"
            "Admin commands require Telegram permissions. Clone only with permission.</i>\n"
            "<b>╰━━━『 ᴍᴀᴅᴇ ᴡɪᴛʜ ᴢʏʀᴀ 💜 』━━━╯</b>"
        )

    @client.on(events.NewMessage(pattern=r"^" + p + r"alive$", outgoing=True))
    async def alive(e):
        me = await client.get_me()
        await e.edit("<b>ZYRA is online</b>\nAccount: <code>%s</code>" % (me.first_name or me.id))

    @client.on(events.NewMessage(pattern=r"^" + p + r"echo\s+(.+)$", outgoing=True))
    async def echo(e):
        await e.edit(e.pattern_match.group(1))

    @client.on(events.NewMessage(pattern=r"^" + p + r"calc\s+(.+)$", outgoing=True))
    async def calc(e):
        try:
            result = _safe_calc(e.pattern_match.group(1).strip())
            await e.edit("<code>%s</code>" % result)
        except Exception as ex:
            await e.edit("Calculation error: <code>%s</code>" % str(ex)[:150])

    @client.on(events.NewMessage(pattern=r"^" + p + r"reverse\s+(.+)$", outgoing=True))
    async def reverse(e):
        await e.edit(e.pattern_match.group(1)[::-1])

    @client.on(events.NewMessage(pattern=r"^" + p + r"clap\s+(.+)$", outgoing=True))
    async def clap(e):
        await e.edit(" 👏 ".join(e.pattern_match.group(1).split()))

    @client.on(events.NewMessage(pattern=r"^" + p + r"emojify\s+(.+)$", outgoing=True))
    async def emojify(e):
        marks = ["✨", "🌸", "🖤", "⚡", "💫", "🌙", "🔥"]
        await e.edit(" ".join(w + random.choice(marks) for w in e.pattern_match.group(1).split()))

    @client.on(events.NewMessage(pattern=r"^" + p + r"spoiler\s+(.+)$", outgoing=True))
    async def spoiler(e):
        text = e.pattern_match.group(1)
        await e.edit("<tg-spoiler>%s</tg-spoiler>" % text.replace("<", "&lt;").replace(">", "&gt;"))

    @client.on(events.NewMessage(pattern=r"^" + p + r"type\s+(.+)$", outgoing=True))
    async def type_text(e):
        text = e.pattern_match.group(1)
        if len(text) > 300:
            return await e.edit("Text limit: 300 characters.")
        await e.edit("...")
        # Edit in small chunks to reduce Telegram edit-rate-limit errors.
        try:
            for i in range(2, len(text) + 1, 2):
                await e.edit(text[:i])
                await asyncio.sleep(0.10)
            if len(text) % 2:
                await e.edit(text)
        except Exception as ex:
            # Leave the last successfully rendered text instead of crashing the handler.
            try:
                await e.edit(text)
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
