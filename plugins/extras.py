"""Safe utility, notes, AFK and auto-reply commands for Zyra Userbot."""
import ast
import asyncio
import html
import operator
import os
import random
import re
import time

from telethon import events
import db as database
from telethon.tl.types import DocumentAttributeSticker
from guard import is_ignored

# In-memory AFK state; reset when the worker restarts.
_AFK = {}


def _render_afk_message(template, sender):
    """Safely render sender placeholders in an AFK reply."""
    first = (getattr(sender, "first_name", None) or "there").strip()
    username = getattr(sender, "username", None) or ""
    sender_id = str(getattr(sender, "id", "") or "")

    # Escape the user-authored template first, then insert escaped sender data.
    rendered = html.escape(template)
    values = {
        "first_name": html.escape(first),
        "name": html.escape(first),
        "username": html.escape("@" + username if username else ""),
        "id": html.escape(sender_id),
        "mention": (
            f'<a href="tg://user?id={html.escape(sender_id, quote=True)}">{html.escape(first)}</a>'
            if sender_id else html.escape(first)
        ),
    }
    return re.sub(
        r"\{(first_name|name|username|id|mention)\}",
        lambda match: values[match.group(1)],
        rendered,
    )


def _env_int(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name, default, minimum, maximum):
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


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
    stickers = database.db.zyra_sticker_replies
    sticker_settings = database.db.zyra_sticker_settings
    sticker_pool = database.db.zyra_sticker_pool
    sticker_cooldowns = {}
    afk_reply_cooldowns = {}
    afk_settings = database.db.zyra_afk_settings
    afk_states = database.db.zyra_afk_states

    # Paginated, quote-style help center. Each page stays compact and explains
    # commands with practical examples. Callback access is restricted to the owner.
    def _help_pages():
        prefix = html.escape(client.prefix)
        return [
            (
                "<b>╭━━━『 🎀 𝐙𝐘𝐑𝐀 · 𝐇𝐄𝐋𝐏 』━━━╮</b>\n"
                "<i>Page 1/5 · Basics & Profile</i>\n\n"
                "<blockquote><b>⚡ BASIC COMMANDS</b>\n"
                f"<code>{prefix}ping</code> — response speed check karo\n"
                f"<code>{prefix}alive</code> — account online hai ya nahi\n"
                f"<code>{prefix}help</code> — ye help guide kholo\n"
                f"<code>{prefix}id</code> — apni/chat ID dekho; kisi ke msg par reply karke uski ID dekho\n\n"
                "<b>👤 PROFILE CLONE / RESTORE</b>\n"
                f"Reply to someone's message: <code>{prefix}clone</code>\n"
                f"<code>{prefix}clone @username</code> — username se profile select karo\n"
                f"<code>{prefix}reclone</code> or <code>{prefix}revert</code> — apni saved profile wapas lagao\n\n"
                "<i>Clone sirf permission lekar karo. Telegram kuch profile details ya photos access nahi karne deta.</i>"
                "</blockquote>\n"
                "<i>Use the buttons below to move through the guide.</i>"
            ),
            (
                "<b>✧ TEXT &amp; COMMUNITY TOOLS</b>\n"
                "<i>Page 2/5 · Text, tags &amp; message rotation</i>\n\n"
                "<blockquote><b>✍️ TEXT UTILITIES</b>\n"
                f"<code>{prefix}echo hello</code> — text dobara bhejo\n"
                f"<code>{prefix}calc 2+2</code> — calculation karo\n"
                f"<code>{prefix}reverse hello</code> — text ulta karo\n"
                f"<code>{prefix}clap hello</code> — har word ke beech clap lagao\n"
                f"<code>{prefix}emojify hello</code> — text mein emojis add karo\n"
                f"<code>{prefix}spoiler text</code> — text ko spoiler banao\n"
                f"<code>{prefix}type hello</code> — typewriter effect se bhejo\n\n"
                "<b>👥 SMART TAGS (GROUP)</b>\n"
                f"<code>{prefix}tagrefresh</code> — group ke available members scan/save karo\n"
                f"<code>{prefix}tagall [message]</code> — saved members ko mention karo (admin only)\n"
                f"<code>{prefix}taglist</code> — saved aur opt-out members ka count dekho\n"
                f"<code>{prefix}tagjoin</code> / <code>{prefix}tagleave</code> — tagging allow/stop karo\n"
                f"<code>{prefix}tagstop</code> — chal raha tag process roko\n"
                f"<code>{prefix}tagclear</code> — is group ki saved member list clear karo\n\n"
                "<b>🔁 MESSAGE ROTATION</b>\n"
                f"<code>{prefix}addraid msg 1 | msg 2</code> — owner shared messages save kare\n"
                f"<code>{prefix}raid 3</code> — shared list se up to 3 messages (10 min chat cooldown)\n"
                f"<code>{prefix}clearraid</code> — owner shared messages delete kare"
                "</blockquote>\n"
                "<i>Telegram har member ko list nahi karta. Sirf available members tag honge; opt-out aur limits apply hongi.</i>"
            ),
            (
                "<b>☾ PERSONAL & AUTO-DROP</b>\n"
                "<i>Page 3/5 · AFK, promo & DM replies</i>\n\n"
                "<blockquote><b>🌙 AFK</b>\n"
                f"<code>{prefix}afk</code> — AFK mode on karo\n"
                f"<code>{prefix}afk busy right now</code> — custom AFK message ke saath on karo\n"
                f"<code>{prefix}afkmsg message</code> — default AFK message save karo\n"
                f"<code>{prefix}afkmsg</code> — saved message dekho\n"
                f"<code>{prefix}afk busy | 2h</code> — reason + auto-expiry\n"
                f"<code>{prefix}afkstats</code> — AFK duration/mentions dekho\n"
                f"<code>{prefix}unafk</code> — AFK mode off karo\n\n"
                "<b>📢 AUTO PROMO</b>\n"
                f"<code>{prefix}promo on</code> / <code>{prefix}promo off</code> — automatic promotion on/off karo\n"
                f"<code>{prefix}promo status</code> — settings dekho\n"
                f"<code>{prefix}promo set your text</code> — promo message set karo (single line)\n"
                f"<code>{prefix}promo add LABEL | URL</code> — promo link save karo\n"
                f"<code>{prefix}promo list</code> / <code>{prefix}promo remove 1</code> — links dekho ya remove karo\n"
                f"<code>{prefix}promo time 12h</code> — promo ka time set karo\n"
                f"<code>{prefix}promo trigger on/off/status</code> — mention/reply promo control\n"
                f"<code>{prefix}promo test</code> — promo ka test dekho\n\n"
                "<b>💌 DM TRAP</b>\n"
                f"<code>{prefix}dmtrap on</code> / <code>{prefix}dmtrap off</code> — DM reply on/off karo\n"
                f"<code>{prefix}dmtrap set your text</code> — set DM reply\n"
                f"<code>{prefix}dmtrap status</code> — settings dekho\n"
                f"<code>{prefix}dmtrap cooldown</code> / <code>{prefix}dmtrap reset</code> — timing controls"
                "</blockquote>\n"
                "<i>Recurring DM promo sirf un logon ko bhejo jinhone subscribe kiya ho. Telegram limits aur group rules follow karo.</i>"
            ),
            (
                "<b>🗂 NOTES &amp; AUTO REPLIES</b>\n"
                "<i>Page 4/5 · Text triggers & sticker replies</i>\n\n"
                "<blockquote><b>📝 NOTES</b>\n"
                f"<code>{prefix}note name | text</code> — note save karo\n"
                f"<code>{prefix}getnote name</code> — note padho\n"
                f"<code>{prefix}delnote name</code> — note delete karo\n"
                f"<code>{prefix}notes</code> — saare notes dekho\n\n"
                "<b>💬 AUTO-REPLY (ALL CHATS)</b>\n"
                f"<code>{prefix}autoreply hi | Hello!</code> — exact trigger par text reply save karo\n"
                f"<code>{prefix}delreply hi</code> — reply delete karo\n"
                f"<code>{prefix}replies</code> — saved replies dekho\n\n"
                "<b>🔎 CHAT FILTERS (CURRENT CHAT)</b>\n"
                f"<code>{prefix}filter word | reply</code> — message mein word aane par reply bhejo\n"
                f"<code>{prefix}stop word</code> — filter hatao\n"
                f"<code>{prefix}filters</code> — filters dekho\n\n"
                "<b>🎭 AUTO STICKER REPLIES</b>\n"
                f"1. Send/save a Telegram sticker in a chat you can access.\n"
                f"2. Reply to that sticker with <code>{prefix}setsticker hi</code>.\n"
                f"3. An incoming exact <code>hi</code> trigger can send that sticker.\n"
                f"<code>{prefix}stickers</code> — saved sticker triggers dekho\n"
                f"<code>{prefix}delsticker hi</code> — sticker trigger hatao\n"
                f"<code>{prefix}sticker on</code> / <code>{prefix}sticker off</code> — sticker reply on/off karo\n"
                f"<code>{prefix}sticker status</code> — sticker reply status dekho\n"
                f"<code>{prefix}stickeradd</code> — reply sticker ko response pool mein add karo\n"
                f"<code>{prefix}stickerpool on/off</code> — sticker-to-sticker mode\n"
                f"<code>{prefix}stickerpool</code> / <code>{prefix}stickerclear</code> — pool manage karo"
                "</blockquote>\n"
                "<i>Auto-reply poore message se match hota hai. Filter message ke andar word dhoondhta hai. Sticker reply exact trigger par chalta hai aur cooldown bhi hai.</i>"
            ),
            (
                "<b>⚒ ADMIN, AI &amp; SETTINGS</b>\n"
                "<i>Page 5/5 · Extra help</i>\n\n"
                "<blockquote><b>🛡 GROUP ADMIN</b>\n"
                f"<code>{prefix}adminhelp</code> — group moderation commands ki guide kholo\n"
                "Admin commands tabhi chalenge jab tumhare account ke paas group mein required permissions hon.\n\n"
                "<b>🚫 IGNORE CONTROLS</b>\n"
                f"<code>{prefix}ignore @username</code> / reply + <code>{prefix}ignore</code>\n"
                f"<code>{prefix}unignore @username</code> · <code>{prefix}ignored</code>\n"
                f"<code>{prefix}ignorechat</code> / <code>{prefix}unignorechat</code>\n\n"
                "<b>✦ AI</b>\n"
                f"<code>{prefix}ai your question</code> — AI se sawal poochho\n"
                f"<code>{prefix}ai auto on/off</code> — mention/reply par AI response\n"
                f"<code>{prefix}ai sticker on/off</code> — reply-sticker par AI reaction\n"
                f"<code>{prefix}ai status</code> — AI settings dekho\n\n"
                "<b>🎛 DASHBOARD</b>\n"
                f"<code>{prefix}dashboard</code> — control dashboard kholo\n"
                f"<code>{prefix}dashboard promo</code> — Auto Promo settings\n"
                f"<code>{prefix}dashboard dm</code> — DM Trap settings\n"
                f"<code>{prefix}dashboard tags</code> — Smart Tags settings\n"
                f"<code>{prefix}dashboard ai</code> — AI settings"
                "</blockquote>\n"
                "<i>Prefix tumhari config ke hisaab se hai. Kuch features ke liye Render variables/API keys chahiye. Login code aur 2-step password kisi ko mat dena.</i>\n\n"
                "<b>╰━━━『 ᴍᴀᴅ𝐄 𝐖𝐈𝐓𝐇 𝐙𝐘𝐑𝐀 💜 』━━━╯</b>"
            ),
        ]

    @client.on(events.NewMessage(pattern=r"^" + p + r"help(?:\s+(\d+))?$", outgoing=True))
    async def help_cmd(e):
        pages = _help_pages()
        try:
            page = int(e.pattern_match.group(1) or "1") - 1
        except (TypeError, ValueError):
            page = 0
        if page < 0 or page >= len(pages):
            return await e.edit(
                "❌ Help page not found. Use <code>%shelp</code> to open page 1 or <code>%shelp 1-5</code> to choose a page."
                % (html.escape(client.prefix), html.escape(client.prefix)),
                parse_mode="html",
            )
        prefix = html.escape(client.prefix)
        nav = []
        if page > 0:
            nav.append(f"‹ Previous: <code>{prefix}help {page}</code>")
        if page < len(pages) - 1:
            nav.append(f"Next: <code>{prefix}help {page + 2}</code> ›")
        nav.append(f"Page <b>{page + 1}/{len(pages)}</b>")
        await e.edit(
            pages[page] + "\n\n<blockquote>" + "  ·  ".join(nav) + "</blockquote>",
            parse_mode="html",
            link_preview=False,
        )


    # Owner-managed shared message rotation library. All connected users can use it,
    # but only the configured owner can change the shared messages.
    raid_store = database.db.zyra_raid_messages
    raid_cooldowns = database.db.zyra_raid_cooldowns
    raid_running = set()
    RAID_OWNER_ID = _env_int("OWNER_ID", 0, 0, 2**63 - 1)
    RAID_MAX_PER_RUN = 3
    RAID_DELAY_SECONDS = 2
    RAID_CHAT_COOLDOWN_SECONDS = 600

    def _is_raid_owner(event):
        return bool(RAID_OWNER_ID and event.sender_id == RAID_OWNER_ID)

    @client.on(events.NewMessage(pattern=r"^" + p + r"addraid(?:\s+([\s\S]+))?$", outgoing=True))
    async def addraid(e):
        if not _is_raid_owner(e):
            return await e.edit("🔒 Shared raid messages sirf configured owner update kar sakta hai.")
        raw = (e.pattern_match.group(1) or "").strip()
        msgs = [part.strip() for part in raw.split("|") if part.strip()]
        if not msgs:
            return await e.edit("Usage: <code>%saddraid message 1 | message 2 | message 3</code>" % html.escape(client.prefix))
        if len(msgs) > 20 or any(len(m) > 1000 for m in msgs):
            return await e.edit("Limit: maximum 20 messages; each message up to 1000 characters.")
        await raid_store.update_one(
            {"_id": "owner_shared_raid_messages"},
            {"$set": {"owner_id": RAID_OWNER_ID, "messages": msgs, "updated_at": time.time()}},
            upsert=True,
        )
        await e.edit("✅ Owner ke <b>%d shared messages</b> save ho gaye. Ab connected users <code>%sraid</code> se use kar sakte hain." % (len(msgs), html.escape(client.prefix)))

    @client.on(events.NewMessage(pattern=r"^" + p + r"(?:clearraid|deltraid|delraid)$", outgoing=True))
    async def clearraid(e):
        if not _is_raid_owner(e):
            return await e.edit("🔒 Shared raid messages sirf configured owner delete kar sakta hai.")
        await raid_store.delete_one({"_id": "owner_shared_raid_messages"})
        raid_running.discard(e.chat_id)
        await e.edit("🗑️ Owner ke shared rotation messages clear ho gaye.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"raid(?:\s+(\d+))?$", outgoing=True))
    async def raid(e):
        count = int(e.pattern_match.group(1) or RAID_MAX_PER_RUN)
        if count < 1 or count > RAID_MAX_PER_RUN:
            return await e.edit("Choose 1–%d messages per run. Shared rotation has a chat cooldown." % RAID_MAX_PER_RUN)
        doc = await raid_store.find_one({"_id": "owner_shared_raid_messages"})
        msgs = (doc or {}).get("messages", [])
        if not msgs:
            return await e.edit("Owner ne abhi shared messages save nahi kiye.")
        if e.chat_id in raid_running:
            return await e.edit("A rotation is already running here. Use <code>%sstop</code> to stop it." % html.escape(client.prefix))
        now = time.time()
        cooldown = await raid_cooldowns.find_one({"chat_id": e.chat_id})
        next_allowed = float((cooldown or {}).get("next_allowed", 0))
        if next_allowed > now:
            remaining = int(next_allowed - now)
            return await e.edit("⏳ Is chat mein rotation cooldown active hai. %d sec baad try karo." % remaining)
        await raid_cooldowns.update_one(
            {"chat_id": e.chat_id},
            {"$set": {"next_allowed": now + RAID_CHAT_COOLDOWN_SECONDS}},
            upsert=True,
        )
        await e.delete()
        raid_running.add(e.chat_id)
        try:
            for i in range(min(count, len(msgs))):
                if e.chat_id not in raid_running:
                    break
                await client.send_message(e.chat_id, msgs[i])
                if i + 1 < min(count, len(msgs)):
                    await asyncio.sleep(RAID_DELAY_SECONDS)
        finally:
            raid_running.discard(e.chat_id)

    @client.on(events.NewMessage(pattern=r"^" + p + r"stop$", outgoing=True))
    async def stop_raid(e):
        if e.chat_id in raid_running:
            raid_running.discard(e.chat_id)
            await e.edit("⏹️ Message rotation stopped.")
        else:
            await e.edit("No active rotation in this chat.")

    # Group-wise participant index. New chatters are saved automatically;
    # .tagrefresh can also index all participants Telegram exposes to this account.
    tagall_members = database.db.zyra_tagall_member_entries
    tagall_running = {}
    tagall_runs = database.db.zyra_tagall_runs
    TAGALL_MEMBER_LIMIT = _env_int("TAGALL_MAX_MEMBERS", 50, 10, 200)
    TAGALL_BATCH_SIZE = 1
    TAGALL_DELAY_SECONDS = _env_float("TAGALL_DELAY_SECONDS", 4.0, 3.0, 30.0)
    TAGALL_COOLDOWN_SECONDS = _env_int("TAGALL_COOLDOWN", 3600, 1800, 604800)

    async def save_tag_member(chat_id, sender):
        if not sender or not getattr(sender, "id", None):
            return
        if getattr(sender, "bot", False) or getattr(sender, "deleted", False):
            return
        await tagall_members.update_one(
            {"uid": uid, "chat_id": int(chat_id), "user_id": int(sender.id)},
            {"$set": {
                "name": (getattr(sender, "first_name", None) or getattr(sender, "title", None) or "Member")[:80],
                "username": getattr(sender, "username", None) or "",
                "seen_at": time.time(),
                "is_bot": False,
            }, "$setOnInsert": {"opted_out": False}},
            upsert=True,
        )

    @client.on(events.NewMessage(incoming=True))
    async def track_tagall_active_member(event):
        if not event.is_group or not event.sender_id or event.sender_id == uid:
            return
        try:
            await save_tag_member(event.chat_id, await event.get_sender())
        except Exception:
            # Indexing is best-effort and must never interrupt normal message handling.
            return

    async def _tagall_is_group_admin(chat_id):
        try:
            permissions = await client.get_permissions(chat_id, uid)
            return bool(getattr(permissions, "is_admin", False) or getattr(permissions, "is_creator", False))
        except Exception:
            return False

    async def refresh_group_members(chat_id, status=None):
        """Index all participants visible through Telegram's participant API."""
        scanned = saved = skipped = 0
        async for participant in client.iter_participants(chat_id, limit=TAGALL_MEMBER_LIMIT):
            scanned += 1
            if getattr(participant, "bot", False) or getattr(participant, "deleted", False):
                skipped += 1
                continue
            await save_tag_member(chat_id, participant)
            saved += 1
            if status and scanned % 200 == 0:
                try:
                    await status.edit(
                        f"🔎 <b>ZYRA MEMBER SCAN</b>\n\n"
                        f"Scanned: <b>{scanned}</b>\nSaved: <b>{saved}</b>\n"
                        f"Skipped bots/deleted: <b>{skipped}</b>", parse_mode="html"
                    )
                except Exception:
                    pass
        return scanned, saved, skipped

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagrefresh$", outgoing=True))
    async def tagall_refresh(e):
        if not e.is_group:
            return await e.edit("This command works only in groups.")
        if not await _tagall_is_group_admin(e.chat_id):
            return await e.edit("⛔ <b>Admin-only.</b> Connected account must be a group admin.")
        status = await e.edit("🔎 <b>ZYRA MEMBER SCAN</b>\nTelegram se visible group members search ho rahe hain…")
        try:
            scanned, saved, skipped = await refresh_group_members(e.chat_id, status)
            await status.edit(
                "✅ <b>MEMBER SCAN COMPLETE</b>\n\n"
                f"• Scanned: <b>{scanned}</b>\n• Saved/updated: <b>{saved}</b>\n"
                f"• Skipped: <b>{skipped}</b>\n\n"
                f"Use <code>{client.prefix}tagall your message</code> to mention indexed members.",
                parse_mode="html",
            )
        except Exception as ex:
            await status.edit("⚠️ <b>Member scan failed.</b> Telegram may restrict participant access.\n<code>%s</code>" % html.escape(str(ex)[:220]), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"taglist$", outgoing=True))
    async def tagall_list(e):
        if not e.is_group:
            return await e.edit("Use this command inside a group.")
        total = await tagall_members.count_documents({"uid": uid, "chat_id": int(e.chat_id)})
        excluded = await tagall_members.count_documents({"uid": uid, "chat_id": int(e.chat_id), "opted_out": True})
        await e.edit(f"✦ <b>ZYRA TAG INDEX</b>\nSaved members: <b>{total}</b>\nOpted out: <b>{excluded}</b>\nEligible: <b>{max(0, total-excluded)}</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagclear$", outgoing=True))
    async def tagall_clear(e):
        if not e.is_group or not await _tagall_is_group_admin(e.chat_id):
            return await e.edit("⛔ Group admin only.")
        result = await tagall_members.delete_many({"uid": uid, "chat_id": int(e.chat_id)})
        await e.edit(f"🧹 Cleared <b>{result.deleted_count}</b> saved member records for this group.", parse_mode="html")

    # Any group member can opt out/in by sending the command in that group.
    @client.on(events.NewMessage(pattern=r"^" + p + r"tagleave$"))
    async def tagall_optout(e):
        if not e.is_group or not e.sender_id:
            return
        await tagall_members.update_one(
            {"uid": uid, "chat_id": int(e.chat_id), "user_id": int(e.sender_id)},
            {"$set": {"opted_out": True}}, upsert=True,
        )
        if e.out:
            await e.edit("You are excluded from future ZYRA TagAll mentions.")
        else:
            await e.reply("You are excluded from future ZYRA TagAll mentions.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagjoin$"))
    async def tagall_optin(e):
        if not e.is_group or not e.sender_id:
            return
        await tagall_members.update_one(
            {"uid": uid, "chat_id": int(e.chat_id), "user_id": int(e.sender_id)},
            {"$set": {"opted_out": False, "seen_at": time.time()}}, upsert=True,
        )
        if e.out:
            await e.edit("You are included in future ZYRA TagAll mentions.")
        else:
            await e.reply("You are included in future ZYRA TagAll mentions.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagall(?:\s+([\s\S]+))?$", outgoing=True))
    async def tagall(e):
        if not e.is_group:
            return await e.edit("This command works only in groups.")
        if not await _tagall_is_group_admin(e.chat_id):
            return await e.edit("⛔ <b>Admin-only command.</b> Your connected account must be a group admin.")
        key = (uid, int(e.chat_id))
        if key in tagall_running:
            return await e.edit(f"A TagAll process is already running. Use <code>{client.prefix}tagstop</code>.")
        last_run = await tagall_runs.find_one({"uid": uid, "chat_id": int(e.chat_id)})
        remaining = TAGALL_COOLDOWN_SECONDS - (time.time() - float((last_run or {}).get("last_started", 0)))
        if remaining > 0:
            return await e.edit(f"⏳ TagAll cooldown active. Try again in <b>{int(remaining//60)+1} min</b>.", parse_mode="html")

        custom = (e.pattern_match.group(1) or "").strip()[:500]
        if not custom:
            custom = "👋 Group announcement — please check this message."
        status = await e.edit("🔎 <b>ZYRA TAGALL</b>\nRefreshing group member list…")
        stop_event = asyncio.Event()
        tagall_running[key] = stop_event
        try:
            try:
                scanned, saved, skipped = await refresh_group_members(e.chat_id, status)
            except Exception as ex:
                await status.edit("⚠️ Could not search all group members.\n<code>%s</code>\nWill use members already indexed from group activity." % html.escape(str(ex)[:180]), parse_mode="html")
            cursor = tagall_members.find({"uid": uid, "chat_id": int(e.chat_id), "opted_out": {"$ne": True}}).sort("seen_at", -1).limit(TAGALL_MEMBER_LIMIT)
            members = await cursor.to_list(length=TAGALL_MEMBER_LIMIT)
            if not members:
                return await status.edit("No eligible members found. Try <code>%stagrefresh</code>." % client.prefix, parse_mode="html")
            await tagall_runs.update_one({"uid": uid, "chat_id": int(e.chat_id)}, {"$set": {"last_started": time.time(), "member_count": len(members)}}, upsert=True)
            await status.edit(
                "📣 <b>ZYRA TAGALL STARTED</b>\n"
                f"Eligible members: <b>{len(members)}</b>\n"
                f"Format: <b>1 member per message</b> · Delay: <b>{TAGALL_DELAY_SECONDS:g}s</b>\n"
                f"Stop: <code>{client.prefix}tagstop</code>", parse_mode="html"
            )
            sent_batches = failed_batches = 0
            for offset in range(0, len(members), TAGALL_BATCH_SIZE):
                if stop_event.is_set():
                    break
                batch = members[offset:offset + TAGALL_BATCH_SIZE]
                mentions = []
                for member in batch:
                    member_id = int(member.get("user_id", 0) or 0)
                    if not member_id:
                        continue
                    display = html.escape((member.get("name") or "Member")[:64])
                    mentions.append(f'<a href="tg://user?id={member_id}">{display}</a>')
                if not mentions:
                    continue
                payload = f"<blockquote><b>{html.escape(custom)}</b>\n{mentions[0]}</blockquote>"
                try:
                    await client.send_message(e.chat_id, payload, parse_mode="html", link_preview=False)
                    sent_batches += 1
                except Exception as ex:
                    wait_seconds = getattr(ex, "seconds", None)
                    if wait_seconds is not None:
                        await status.edit(f"⏳ Telegram rate limit — waiting {int(wait_seconds)} seconds.\nSent batches: {sent_batches}", parse_mode="html")
                        await asyncio.sleep(max(1, int(wait_seconds) + 1))
                        if stop_event.is_set():
                            break
                        try:
                            await client.send_message(e.chat_id, payload, parse_mode="html", link_preview=False)
                            sent_batches += 1
                        except Exception:
                            failed_batches += 1
                    else:
                        failed_batches += 1
                if (offset // TAGALL_BATCH_SIZE + 1) % 10 == 0:
                    try:
                        await status.edit(
                            f"📣 <b>ZYRA TAGALL RUNNING</b>\n"
                            f"Progress: <b>{min(100, int((offset+len(batch))*100/len(members)))}%</b>\n"
                            f"Messages sent: <b>{sent_batches}</b> · Failed: <b>{failed_batches}</b>\n"
                            f"Use <code>{client.prefix}tagstop</code> to stop.", parse_mode="html"
                        )
                    except Exception:
                        pass
                if offset + TAGALL_BATCH_SIZE < len(members) and not stop_event.is_set():
                    await asyncio.sleep(TAGALL_DELAY_SECONDS)
            result = "🛑 <b>TAGALL STOPPED</b>" if stop_event.is_set() else "✅ <b>TAGALL COMPLETED</b>"
            await status.edit(f"{result}\n\nMembers indexed: <b>{len(members)}</b>\nMessages sent: <b>{sent_batches}</b>\nFailed messages: <b>{failed_batches}</b>", parse_mode="html")
        finally:
            tagall_running.pop(key, None)

    @client.on(events.NewMessage(pattern=r"^" + p + r"(?:tagstop|tagcancel)$", outgoing=True))
    async def tagall_cancel(e):
        running = tagall_running.get((uid, int(e.chat_id)))
        if running:
            running.set()
            await e.edit("🛑 <b>ZYRA TagAll stop requested.</b>")
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
            cached = _AFK[uid]
            if cached.get("expires_at") and time.time() >= float(cached["expires_at"]):
                _AFK.pop(uid, None)
                await afk_states.update_one({"uid": uid}, {"$set": {"active": False}})
                return None
            return cached
        doc = await afk_states.find_one({"uid": uid})
        if doc and doc.get("active"):
            expires = doc.get("expires_at")
            if expires and time.time() >= float(expires):
                await afk_states.update_one({"uid": uid}, {"$set": {"active": False}})
                return None
            _AFK[uid] = {"message": doc.get("message", "I'm currently AFK."), "since": doc.get("since", time.time()), "reason": doc.get("reason", ""), "expires_at": expires}
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
        raw = (e.pattern_match.group(1) or "").strip()
        reason, duration = raw, None
        if "|" in raw:
            reason, duration = [x.strip() for x in raw.rsplit("|", 1)]
        expires_at = None
        if duration:
            match = re.fullmatch(r"(\d+)(m|h|d)", duration.lower())
            if not match:
                return await e.edit("Duration format: <code>.afk busy | 2h</code> (m/h/d).")
            amount = int(match.group(1)); unit = match.group(2)
            if amount < 1 or amount > 30:
                return await e.edit("Duration 1–30 units ke beech rakho.")
            expires_at = time.time() + amount * {"m": 60, "h": 3600, "d": 86400}[unit]
        if not reason:
            doc = await afk_settings.find_one({"uid": uid})
            reason = doc.get("message") if doc else "I'm currently AFK. I'll reply when I'm back."
        message = reason if "|" not in raw or reason else "I'm currently AFK."
        if len(message) > 3500:
            return await e.edit("AFK message is too long. Maximum: 3500 characters.")
        since = time.time()
        _AFK[uid] = {"message": message, "since": since, "reason": message, "expires_at": expires_at}
        await afk_states.update_one({"uid": uid}, {"$set": {"active": True, "message": message, "reason": message, "since": since, "expires_at": expires_at, "mention_count": 0}}, upsert=True)
        suffix = "\nAuto-expiry: <b>%s</b>" % html.escape(duration) if duration else ""
        await e.edit("🎀 <b>AFK enabled</b>\nReason: %s%s\n\nUse <code>%sunafk</code> to return." % (html.escape(message[:250]), suffix, client.prefix))

    @client.on(events.NewMessage(pattern=r"^" + p + r"afkstats$", outgoing=True))
    async def afk_stats(e):
        await load_afk_state()
        doc = await afk_states.find_one({"uid": uid}) or {}
        active = bool(doc.get("active"))
        since = float(doc.get("since", time.time()))
        duration = max(0, int(time.time() - since)) if active else 0
        expires = doc.get("expires_at")
        remaining = max(0, int(expires - time.time())) if expires else None
        def fmt(seconds):
            return "%dh %dm" % (seconds // 3600, (seconds % 3600) // 60)
        await e.edit("<b>🌙 ZYRA AFK STATS</b>\nStatus: <b>%s</b>\nReason: %s\nDuration: <b>%s</b>\nMentions: <b>%s</b>\nRemaining: <b>%s</b>" % (
            "ON" if active else "OFF", html.escape(doc.get("reason", doc.get("message", "—"))[:180]), fmt(duration),
            int(doc.get("mention_count", 0)), fmt(remaining) if remaining is not None else "No auto-expiry"))

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
        if getattr(e, "sender_id", None) == client.me_id:
            return
        if await is_ignored(uid, e.sender_id, e.chat_id):
            return
        afk_data = await load_afk_state()
        if afk_data and e.sender_id and (e.is_private or e.mentioned):
            try:
                now = time.monotonic()
                if now - afk_reply_cooldowns.get((e.chat_id, e.sender_id), 0) >= 300:
                    afk_reply_cooldowns[(e.chat_id, e.sender_id)] = now
                    sender = await e.get_sender()
                    reply_text = _render_afk_message(afk_data["message"], sender)
                    await e.reply(reply_text, parse_mode="html")
                    await afk_states.update_one({"uid": uid}, {"$inc": {"mention_count": 1}})
                return
            except Exception:
                pass
        text = (e.raw_text or "").strip()
        # Sticker-to-sticker mode: any incoming sticker can trigger a saved sticker response.
        if e.sticker:
            pool_cfg = await sticker_settings.find_one({"uid": uid}) or {}
            if pool_cfg.get("enabled", True) and pool_cfg.get("sticker_to_sticker", False):
                pool = await sticker_pool.find({"uid": uid}).to_list(length=50)
                if pool:
                    key = (e.chat_id, e.sender_id, "sticker-pool")
                    now = time.monotonic()
                    if now - sticker_cooldowns.get(key, 0) >= 30:
                        sticker_cooldowns[key] = now
                        chosen = random.choice(pool)
                        try:
                            source = await client.get_messages(chosen["source_chat_id"], ids=chosen["source_message_id"])
                            if source and source.media:
                                await client.send_file(e.chat_id, source, reply_to=e.id)
                        except Exception:
                            pass
        # Sticker replies use exact, case-insensitive text trigger matches.
        sticker_cfg = await sticker_settings.find_one({"uid": uid})
        if sticker_cfg is None or sticker_cfg.get("enabled", True):
            sticker_doc = await stickers.find_one({"uid": uid, "trigger": text.casefold()})
            if sticker_doc:
                cooldown_key = (e.chat_id, e.sender_id, text.casefold())
                now = time.monotonic()
                if now - sticker_cooldowns.get(cooldown_key, 0) >= 30:
                    sticker_cooldowns[cooldown_key] = now
                    try:
                        source = await client.get_messages(sticker_doc["source_chat_id"], ids=sticker_doc["source_message_id"])
                        if source and source.media:
                            await client.send_file(e.chat_id, source, reply_to=e.id)
                    except Exception:
                        # Keep the listener alive if a saved source message was deleted or unavailable.
                        pass
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


    @client.on(events.NewMessage(pattern=r"^" + p + r"setsticker\s+(.+)$", outgoing=True))
    async def set_sticker_reply(e):
        trigger = e.pattern_match.group(1).strip().casefold()
        if not e.is_reply:
            return await e.edit("Reply to a Telegram sticker with <code>%ssetsticker trigger</code>." % client.prefix)
        source = await e.get_reply_message()
        is_sticker = bool(
            source and source.document and any(
                isinstance(attr, DocumentAttributeSticker) for attr in (source.document.attributes or [])
            )
        )
        if not is_sticker:
            return await e.edit("❌ Reply to an actual Telegram sticker, then use this command.")
        await stickers.update_one(
            {"uid": uid, "trigger": trigger},
            {"$set": {"trigger": trigger, "source_chat_id": source.chat_id, "source_message_id": source.id}},
            upsert=True,
        )
        await e.edit("🎭 Sticker reply saved for <code>%s</code>." % html.escape(trigger))

    @client.on(events.NewMessage(pattern=r"^" + p + r"delsticker\s+(.+)$", outgoing=True))
    async def delete_sticker_reply(e):
        trigger = e.pattern_match.group(1).strip().casefold()
        result = await stickers.delete_one({"uid": uid, "trigger": trigger})
        await e.edit("🗑 Sticker reply removed." if result.deleted_count else "Sticker trigger not found.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"stickers$", outgoing=True))
    async def list_sticker_replies(e):
        items = await stickers.find({"uid": uid}).to_list(length=100)
        lines = ["• <code>%s</code>" % html.escape(item["trigger"]) for item in items]
        await e.edit("🎭 <b>Saved sticker triggers</b>\n" + ("\n".join(lines) if lines else "No sticker replies saved."))

    @client.on(events.NewMessage(pattern=r"^" + p + r"stickeradd$", outgoing=True))
    async def sticker_pool_add(e):
        if not e.is_reply:
            return await e.edit("Reply to a sticker with <code>%sstickeradd</code> to add it to the response pool." % client.prefix)
        source = await e.get_reply_message()
        is_sticker = bool(source and source.document and any(isinstance(a, DocumentAttributeSticker) for a in (source.document.attributes or [])))
        if not is_sticker:
            return await e.edit("Please reply to an actual Telegram sticker.")
        await sticker_pool.update_one({"uid": uid, "source_chat_id": source.chat_id, "source_message_id": source.id},
            {"$set": {"added_at": time.time()}}, upsert=True)
        await e.edit("🎭 Sticker added to sticker-to-sticker pool.")

    @client.on(events.NewMessage(pattern=r"^" + p + r"stickerpool$", outgoing=True))
    async def sticker_pool_list(e):
        items = await sticker_pool.find({"uid": uid}).to_list(length=50)
        cfg = await sticker_settings.find_one({"uid": uid}) or {}
        await e.edit("<b>🎭 STICKER RESPONSE POOL</b>\nSaved: <b>%s</b>\nSticker-to-sticker: <b>%s</b>\n\nUse <code>%sstickeradd</code> replying to a sticker, then <code>%sstickerpool on</code>." %
            (len(items), "ON" if cfg.get("sticker_to_sticker") else "OFF", client.prefix, client.prefix))

    @client.on(events.NewMessage(pattern=r"^" + p + r"stickerpool\s+(on|off)$", outgoing=True))
    async def sticker_pool_toggle(e):
        enabled = e.pattern_match.group(1) == "on"
        await sticker_settings.update_one({"uid": uid}, {"$set": {"sticker_to_sticker": enabled}}, upsert=True)
        await e.edit("Sticker-to-sticker mode <b>%s</b>." % ("ON ✅" if enabled else "OFF ⏸"))

    @client.on(events.NewMessage(pattern=r"^" + p + r"stickerclear$", outgoing=True))
    async def sticker_pool_clear(e):
        result = await sticker_pool.delete_many({"uid": uid})
        await e.edit("🗑 Cleared <b>%s</b> saved stickers." % result.deleted_count)

    @client.on(events.NewMessage(pattern=r"^" + p + r"sticker\s+(on|off|status)$", outgoing=True))
    async def sticker_reply_control(e):
        action = e.pattern_match.group(1).lower()
        cfg = await sticker_settings.find_one({"uid": uid}) or {"enabled": True}
        if action == "status":
            enabled = cfg.get("enabled", True)
            return await e.edit("🎭 Auto Sticker Reply: <b>%s</b>" % ("ON ✅" if enabled else "OFF ⏸"))
        enabled = action == "on"
        await sticker_settings.update_one({"uid": uid}, {"$set": {"enabled": enabled}}, upsert=True)
        await e.edit("🎭 Auto Sticker Reply <b>%s</b>." % ("enabled ✅" if enabled else "paused ⏸"))
