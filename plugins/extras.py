"""Safe utility, notes, AFK and auto-reply commands for Zyra Userbot."""
import ast
import asyncio
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

    @client.on(events.NewMessage(pattern=r"^" + p + r"help$", outgoing=True))
    async def help_cmd(e):
        await e.edit(
            "<b>ZYRA USERBOT · HELP</b>\n\n"
            "<b>Basic:</b> <code>.ping</code> · <code>.alive</code> · <code>.help</code>\n"
            "<b>Utilities:</b> <code>.calc 2+2</code> · <code>.echo text</code> · "
            "<code>.reverse text</code> · <code>.clap text</code> · <code>.emojify text</code>\n"
            "<b>Text:</b> <code>.spoiler text</code> · <code>.type text</code>\n"
            "<b>AFK:</b> <code>.afk reason</code> · <code>.unafk</code>\n"
            "<b>Notes:</b> <code>.note name | content</code> · <code>.getnote name</code> · "
            "<code>.delnote name</code> · <code>.notes</code>\n"
            "<b>Auto replies:</b> <code>.autoreply trigger | response</code> · "
            "<code>.delreply trigger</code> · <code>.replies</code>\n"
            "<b>Filters:</b> <code>.filter trigger | response</code> · "
            "<code>.stop trigger</code> · <code>.filters</code>\n"
            "<b>Admin:</b> <code>.adminhelp</code> · <code>.ban</code> · <code>.unban</code> · "
            "<code>.mute</code> · <code>.unmute</code> · <code>.kick</code> · <code>.purge 20</code> · "
            "<code>.pin</code> · <code>.unpin</code> · <code>.del</code> · <code>.admins</code> · <code>.id</code>\n\n"
            "Commands use your configured prefix. Group moderation commands may require admin rights."
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

    @client.on(events.NewMessage(pattern=r"^" + p + r"afk(?:\s+(.+))?$", outgoing=True))
    async def afk(e):
        reason = (e.pattern_match.group(1) or "Away").strip()[:200]
        _AFK[uid] = {"reason": reason, "since": time.time()}
        await e.edit("AFK enabled: <b>%s</b>" % reason)

    @client.on(events.NewMessage(pattern=r"^" + p + r"unafk$", outgoing=True))
    async def unafk(e):
        old = _AFK.pop(uid, None)
        if old:
            await e.edit("Welcome back! AFK was on for %d seconds." % int(time.time() - old["since"]))
        else:
            await e.edit("AFK was not enabled.")

    @client.on(events.NewMessage(incoming=True))
    async def incoming(e):
        if not e.raw_text or getattr(e, "sender_id", None) == client.me_id:
            return
        afk_data = _AFK.get(uid)
        if afk_data and e.sender_id and (e.is_private or e.mentioned):
            try:
                await e.reply("I'm currently AFK: %s" % afk_data["reason"])
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
