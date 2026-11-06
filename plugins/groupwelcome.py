"""Group member archive and per-group welcome tools for Zyra UserBot."""
import asyncio
import html
import io
import logging
import re
import time

from telethon import Button, events, utils
from telethon.errors import FloodWaitError
from pymongo import UpdateOne
import db as database

log = logging.getLogger("zyra.groupwelcome")
MAX_IMPORT_MEMBERS = 5000
TAGALL_LIMIT = 150


def _make_welcome_image(name, group_name, avatar_bytes=None, background_bytes=None):
    """Render a member-specific black/purple neon welcome card."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    size = (1280, 720)
    try:
        if background_bytes:
            bg = Image.open(io.BytesIO(background_bytes)).convert("RGB").resize(size)
        else:
            bg = Image.new("RGB", size, (12, 7, 24))
            px = bg.load()
            for y in range(size[1]):
                for x in range(size[0]):
                    glow = max(0, 1 - (((x - 980) / 700) ** 2 + ((y - 180) / 550) ** 2))
                    px[x, y] = (int(12 + 45 * glow), int(7 + 8 * glow), int(25 + 95 * glow))
        overlay = Image.new("RGBA", size, (5, 3, 15, 125))
        bg = Image.alpha_composite(bg.convert("RGBA"), overlay)
        draw = ImageDraw.Draw(bg)
        # Neon frame and accent lines.
        draw.rounded_rectangle((34, 34, 1246, 686), radius=42, outline=(177, 76, 255, 230), width=5)
        draw.rounded_rectangle((48, 48, 1232, 672), radius=34, outline=(94, 42, 160, 180), width=2)

        try:
            font_bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
            font_name = ImageFont.truetype("DejaVuSans-Bold.ttf", 58)
            font_small = ImageFont.truetype("DejaVuSans.ttf", 30)
        except Exception:
            font_bold = font_name = font_small = ImageFont.load_default()

        # Avatar on the right, with a purple ring.
        if avatar_bytes:
            try:
                avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
                side = min(avatar.size)
                left = (avatar.width - side) // 2
                top = (avatar.height - side) // 2
                avatar = avatar.crop((left, top, left + side, top + side)).resize((300, 300))
                mask = Image.new("L", (300, 300), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, 299, 299), fill=255)
                draw.ellipse((865, 170, 1195, 500), outline=(206, 111, 255, 255), width=13)
                bg.paste(avatar, (880, 185), mask)
            except Exception:
                log.debug("Could not render member avatar", exc_info=True)

        draw.text((105, 190), "WELCOME", font=font_bold, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(123, 48, 210, 255))
        draw.text((105, 285), "TO MY GROUP", font=font_bold, fill=(205, 133, 255, 255))
        safe_name = (name or "New Member").strip()[:28]
        draw.text((108, 430), safe_name, font=font_name, fill=(255, 255, 255, 255))
        draw.text((110, 515), (group_name or "Our Community")[:42], font=font_small, fill=(210, 195, 235, 255))
        draw.text((110, 610), "✦  ZYRA COMMUNITY  ✦", font=font_small, fill=(186, 119, 255, 255))
        out = io.BytesIO()
        bg.convert("RGB").save(out, format="JPEG", quality=90, optimize=True)
        out.seek(0)
        return out
    except Exception:
        log.exception("Welcome image render failed")
        return None


def setup(client):
    p = re.escape(client.prefix)
    uid = client.uid
    members = database.db.zyra_group_members
    welcome = database.db.zyra_group_welcome
    tagall_store = database.db.zyra_tagall_members
    member_index_ready = False
    welcome_index_ready = False

    async def ensure_indexes():
        nonlocal member_index_ready, welcome_index_ready
        if not member_index_ready:
            try:
                await members.create_index(
                    [("uid", 1), ("chat_id", 1), ("member_id", 1)],
                    unique=True, name="zyra_group_member_unique"
                )
            except Exception:
                log.exception("Could not ensure unique group-member index")
            member_index_ready = True
        if not welcome_index_ready:
            try:
                await welcome.create_index(
                    [("uid", 1), ("chat_id", 1)],
                    unique=True, name="zyra_group_welcome_unique"
                )
            except Exception:
                log.exception("Could not ensure unique group-welcome index")
            welcome_index_ready = True

    async def is_admin(chat_id):
        try:
            perms = await client.get_permissions(chat_id, uid)
            return bool(getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False))
        except Exception:
            return False

    async def save_member(chat_id, sender):
        if not sender or getattr(sender, "bot", False) or getattr(sender, "deleted", False):
            return False
        await ensure_indexes()
        now = time.time()
        info = {
            "uid": uid, "chat_id": int(chat_id), "member_id": int(sender.id),
            "first_name": (getattr(sender, "first_name", None) or "Member")[:128],
            "last_name": (getattr(sender, "last_name", None) or "")[:128],
            "username": getattr(sender, "username", None) or "",
            "last_seen": now,
        }
        await members.update_one(
            {"uid": uid, "chat_id": int(chat_id), "member_id": int(sender.id)},
            {"$set": info, "$setOnInsert": {"joined_at": now}},
            upsert=True,
        )
        return True

    @client.on(events.NewMessage(incoming=True))
    async def auto_archive_member(event):
        if not event.is_group or not event.sender_id or event.sender_id == uid:
            return
        try:
            sender = await event.get_sender()
            await save_member(event.chat_id, sender)
        except Exception:
            log.debug("Member auto-archive failed", exc_info=True)

    async def send_welcome(chat_id, user, cfg=None):
        """Send the configured welcome for one user; shared by joins, tests and preview."""
        if not user:
            return False
        await ensure_indexes()
        cfg = cfg or await welcome.find_one({"uid": uid, "chat_id": int(chat_id)}) or {}
        if not cfg.get("enabled", True):
            return False
        try:
            group = await client.get_entity(chat_id)
        except Exception:
            group = None
        group_name = getattr(group, "title", None) or "Our Group"
        first_name = getattr(user, "first_name", None) or "New Member"
        username = getattr(user, "username", None) or ""
        avatar = None
        try:
            avatar = await client.download_profile_photo(user, file=bytes)
        except Exception:
            pass
        image = _make_welcome_image(first_name, group_name, avatar, cfg.get("background"))
        values = {
            "group_name": group_name,
            "first_name": first_name,
            "username": ("@" + username) if username else "",
            "user_id": str(user.id),
        }
        template = cfg.get("text", "Welcome {first_name} to {group_name}! 💜")
        try:
            caption = template.format(**values)
        except Exception:
            log.warning("Invalid welcome template for chat_id=%s; using default", chat_id)
            caption = f"Welcome {first_name} to {group_name}! 💜"
        caption = html.escape(caption)
        buttons = []
        for item in cfg.get("buttons", [])[:4]:
            label, url = item.get("label"), item.get("url")
            if label and url and re.match(r"^https?://", url, re.I):
                buttons.append(Button.url(label[:40], url))
        if image:
            await client.send_file(chat_id, image, caption=caption, buttons=buttons or None, parse_mode="html")
        else:
            await client.send_message(chat_id, caption, buttons=buttons or None, parse_mode="html")
        return True

    @client.on(events.ChatAction)
    async def archive_joined_member(event):
        """Handle single joins and Telegram service messages adding multiple users."""
        try:
            if not (event.user_joined or event.user_added):
                return
            # Telethon can expose one user or a list when several members are added.
            joined_users = list(getattr(event, "users", None) or [])
            if not joined_users:
                try:
                    one_user = await event.get_user()
                    if one_user:
                        joined_users = [one_user]
                except Exception:
                    pass
            if not joined_users:
                for user_id in (getattr(event, "user_ids", None) or []):
                    try:
                        joined_users.append(await client.get_entity(user_id))
                    except Exception:
                        log.debug("Could not resolve joined user id=%s", user_id)
            if not joined_users:
                log.warning("Join event received without resolvable users chat_id=%s", event.chat_id)
                return
            cfg = await welcome.find_one({"uid": uid, "chat_id": int(event.chat_id)})
            for user in joined_users:
                if not user:
                    continue
                await save_member(event.chat_id, user)
                if cfg and cfg.get("enabled", True):
                    await send_welcome(event.chat_id, user, cfg)
        except Exception:
            log.exception("Group welcome handler failed chat_id=%s", getattr(event, "chat_id", "unknown"))

    async def resolve_target(event, target):
        if event.is_group:
            return event.chat_id
        if target:
            try:
                lookup = int(target) if target.lstrip("-").isdigit() else target
                entity = await client.get_entity(lookup)
                if hasattr(entity, "title"):
                    return int(utils.get_peer_id(entity))
            except Exception:
                return None
        dialogs = await client.get_dialogs(limit=200)
        groups = [d for d in dialogs if d.is_group]
        if len(groups) == 1:
            return groups[0].id
        return None

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagjoin(?:\s+(\S+))?$", outgoing=True))
    async def tagjoin(event):
        target = await resolve_target(event, (event.pattern_match.group(1) or "").strip())
        if not target:
            return await event.edit(
                "📌 <b>Choose a target group</b>\n"
                "Group mein command bhejo, ya private chat mein <code>%stagjoin -1001234567890</code> use karo." % client.prefix,
                parse_mode="html",
            )
        if not await is_admin(target):
            return await event.edit("⛔ Target group mein tumhara connected account admin hona chahiye.")
        status = await event.edit("🪄 <b>Group member import</b>\n<code>2%</code> · Preparing…", parse_mode="html")
        imported = skipped = 0
        try:
            entity = await client.get_entity(target)
            ops = []
            stage = [(2, "Preparing…"), (10, "Connecting to group…"), (35, "Reading available members…")]
            for pct, label in stage:
                await status.edit(f"🪄 <b>Group member import</b>\n<code>{pct}%</code> · {label}", parse_mode="html")
                await asyncio.sleep(0.15)
            async for user in client.iter_participants(entity, limit=MAX_IMPORT_MEMBERS):
                if not user or getattr(user, "bot", False) or getattr(user, "deleted", False):
                    skipped += 1
                    continue
                now = time.time()
                doc = {
                    "uid": uid, "chat_id": int(target), "member_id": int(user.id),
                    "first_name": (getattr(user, "first_name", None) or "Member")[:128],
                    "last_name": (getattr(user, "last_name", None) or "")[:128],
                    "username": getattr(user, "username", None) or "",
                    "last_seen": now,
                }
                ops.append(UpdateOne(
                    {"uid": uid, "chat_id": int(target), "member_id": int(user.id)},
                    {"$set": doc, "$setOnInsert": {"joined_at": now}}, upsert=True
                ))
                if len(ops) >= 250:
                    await members.bulk_write(ops, ordered=False)
                    imported += len(ops)
                    ops = []
            if ops:
                await members.bulk_write(ops, ordered=False)
                imported += len(ops)
            await status.edit("🪄 <b>Group member import</b>\\n<code>55%</code> · Saving member records…", parse_mode="html")
            # Refresh legacy TagAll list from the newest 150 saved users only.
            latest = await members.find(
                {"uid": uid, "chat_id": int(target)}
            ).sort("last_seen", -1).limit(TAGALL_LIMIT).to_list(length=TAGALL_LIMIT)
            active = [{
                "id": x["member_id"], "name": x.get("first_name", "Member"),
                "username": x.get("username", ""), "last_seen": x.get("last_seen", time.time())
            } for x in latest]
            await status.edit("🪄 <b>Group member import</b>\\n<code>90%</code> · Syncing TagAll list…", parse_mode="html")
            await tagall_store.update_one(
                {"uid": uid, "chat_id": int(target)},
                {"$set": {"active_members": active}}, upsert=True
            )
            await status.edit("🪄 <b>Group member import</b>\\n<code>100%</code> · Complete", parse_mode="html")
            await status.edit(
                "💜 <b>TAGJOIN COMPLETED</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"👥 Saved / updated: <b>{imported}</b>\n"
                f"🤖 Skipped: <b>{skipped}</b>\n"
                f"🗂 Group ID: <code>{target}</code>\n"
                "✨ Members are stored separately for this group.",
                parse_mode="html",
            )
        except FloodWaitError as ex:
            await status.edit(f"⏳ Telegram rate limit. Wait {int(ex.seconds)} seconds, then retry.")
        except Exception as ex:
            log.exception("tagjoin failed")
            await status.edit("❌ Import failed: <code>%s</code>" % html.escape(str(ex)[:250]), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagcount$", outgoing=True))
    async def tagcount(event):
        if not event.is_group:
            return await event.edit("Use this command inside a group.")
        count = await members.count_documents({"uid": uid, "chat_id": int(event.chat_id)})
        await event.edit(f"👥 <b>Saved group members:</b> <code>{count}</code>")

    @client.on(events.NewMessage(pattern=r"^" + p + r"taglist$", outgoing=True))
    async def taglist(event):
        if not event.is_group:
            return await event.edit("Use this command inside a group.")
        rows = await members.find({"uid": uid, "chat_id": int(event.chat_id)}).sort("last_seen", -1).limit(25).to_list(length=25)
        if not rows:
            return await event.edit("No saved members yet. Use <code>%stagjoin</code> or wait for members to chat." % client.prefix)
        lines = []
        for row in rows:
            name = html.escape(row.get("first_name") or "Member")
            username = (" @" + html.escape(row["username"])) if row.get("username") else ""
            lines.append(f"• <a href=\"tg://user?id={row['member_id']}\">{name}</a>{username}")
        await event.edit("<b>🗂 Saved members (latest 25)</b>\n" + "\n".join(lines), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"tagclear$", outgoing=True))
    async def tagclear(event):
        if not event.is_group:
            return await event.edit("Use this command inside a group.")
        if not await is_admin(event.chat_id):
            return await event.reply("⛔ <b>Admin-only.</b>", parse_mode="html")
        await event.edit(
            "⚠️ <b>Clear this group's saved member list?</b>\nThis cannot be undone.",
            buttons=[
                [Button.inline("🗑 Confirm clear", data=f"zyratagclear:{event.chat_id}".encode())],
                [Button.inline("Cancel", data=b"zyratagclear:cancel")],
            ], parse_mode="html"
        )

    @client.on(events.CallbackQuery(pattern=rb"^zyratagclear:"))
    async def confirm_tagclear(event):
        if event.sender_id != uid:
            return await event.answer("Only the connected account owner can confirm.", alert=True)
        value = event.data.decode().split(":", 1)[1]
        if value == "cancel":
            await event.edit("Cancelled.")
            return
        chat_id = int(value)
        if not await is_admin(chat_id):
            return await event.answer("Admin permission required.", alert=True)
        await members.delete_many({"uid": uid, "chat_id": chat_id})
        await tagall_store.delete_one({"uid": uid, "chat_id": chat_id})
        await event.edit("🗑️ This group's saved member list has been cleared.")

    async def panel(event, chat_id):
        await ensure_indexes()
        await welcome.update_one(
            {"uid": uid, "chat_id": int(chat_id)},
            {"$setOnInsert": {"enabled": True, "text": "Welcome {first_name} to {group_name}! 💜", "buttons": []}},
            upsert=True,
        )
        cfg = await welcome.find_one({"uid": uid, "chat_id": int(chat_id)}) or {}
        enabled = cfg.get("enabled", True)
        buttons_count = len(cfg.get("buttons", []))
        text_value = cfg.get("text", "Welcome {first_name} to {group_name}! 💜")
        help_text = (
            "🦋 <b>ZYRA · GROUP WELCOME CENTER</b> 🦋\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ <b>Status:</b> {'🟢 ENABLED' if enabled else '🔴 DISABLED'}\n"
            f"🖼 <b>Custom URL buttons:</b> {buttons_count}/4\n"
            f"💬 <b>Current message:</b> <code>{html.escape(text_value[:160])}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>🛠️ COMMAND GUIDE</b>\n"
            f"📝 <code>{client.prefix}welcometext Your message</code> — Set welcome text\n"
            f"🖼 Reply to a photo with <code>{client.prefix}welcomepicture</code> — Set background\n"
            f"🔗 <code>{client.prefix}welcomebutton Rules | https://example.com</code> — Add URL button\n"
            f"🧹 <code>{client.prefix}welcomebuttonclear</code> — Remove all buttons\n"
            "🧪 <code>/testwelcome</code> — Send a test welcome\n"
            "⚙️ <code>/setwelcome</code> — Open this settings panel\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>✨ SUPPORTED VARIABLES</b>\n"
            "👤 <code>{first_name}</code> · 🏠 <code>{group_name}</code>\n"
            "🔖 <code>{username}</code> · 🆔 <code>{user_id}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Tip: Use the buttons below to enable, preview or reset your welcome setup.</i>"
        )
        await event.reply(
            help_text,
            buttons=[
                [Button.inline("🟢 Enable" if not enabled else "🔴 Disable", data=f"zyrawelcome:toggle:{chat_id}".encode()),
                 Button.inline("👁️ Preview", data=f"zyrawelcome:preview:{chat_id}".encode())],
                [Button.inline("🧪 Test Welcome", data=f"zyrawelcome:test:{chat_id}".encode()),
                 Button.inline("🔄 Reset", data=f"zyrawelcome:reset:{chat_id}".encode())],
            ], parse_mode="html"
        )

    @client.on(events.NewMessage(pattern=r"^/setwelcome(?:@\w+)?(?:\s+(-?\d+))?$", outgoing=True))
    async def setwelcome(event):
        target = int(event.pattern_match.group(1)) if event.pattern_match.group(1) else (event.chat_id if event.is_group else None)
        if target is None:
            return await event.reply("💬 <b>Usage:</b> <code>/setwelcome -1001234567890</code>\nSend this command in a group, or provide a group ID in private chat.", parse_mode="html")
        if not await is_admin(target):
            return await event.reply("⛔ <b>Admin permission required.</b> Your connected account must be an admin in the target group.", parse_mode="html")
        await panel(event, target)

    @client.on(events.NewMessage(pattern=r"^/testwelcome(?:@\w+)?(?:\s+(-?\d+))?$", outgoing=True))
    async def testwelcome(event):
        target = int(event.pattern_match.group(1)) if event.pattern_match.group(1) else (event.chat_id if event.is_group else None)
        if target is None:
            return await event.reply("💬 <b>Usage:</b> <code>/testwelcome -1001234567890</code>\nRun this in a group, or provide a group ID in private chat.", parse_mode="html")
        if not await is_admin(target):
            return await event.reply("⛔ <b>Admin permission required.</b> Connected account must be an admin in that group.", parse_mode="html")
        cfg = await welcome.find_one({"uid": uid, "chat_id": int(target)}) or {}
        if not cfg:
            return await event.reply("⚠️ Welcome settings not found. Run <code>/setwelcome</code> first.", parse_mode="html")
        me = await client.get_me()
        try:
            sent = await send_welcome(target, me, cfg)
            if sent:
                await event.reply("🧪 <b>Test welcome sent!</b>\n🖼 Image · 💬 Message · 🔗 Buttons checked using your saved settings.", parse_mode="html")
            else:
                await event.reply("🔴 <b>Welcome is disabled.</b> Enable it from <code>/setwelcome</code> and run the test again.", parse_mode="html")
        except Exception as exc:
            log.exception("Manual test welcome failed chat_id=%s", target)
            await event.reply("❌ <b>Test welcome failed.</b> Check Render logs for the exact error.\n<code>%s</code>" % html.escape(str(exc)[:250]), parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"welcometext\s+([\s\S]+)$", outgoing=True))
    async def set_welcome_text(event):
        if not event.is_group:
            return await event.reply("💬 <b>Group mein use karo.</b>", parse_mode="html")
        if not await is_admin(event.chat_id):
            return await event.reply("⛔ <b>Admin-only.</b>", parse_mode="html")
        value = event.pattern_match.group(1).strip()
        if len(value) > 900:
            return await event.reply("⚠️ <b>Welcome text maximum 900 characters.</b>", parse_mode="html")
        await welcome.update_one({"uid": uid, "chat_id": int(event.chat_id)}, {"$set": {"text": value}}, upsert=True)
        await event.reply("💜 <b>Welcome text saved!</b> Use <code>/setwelcome</code> to open settings.", parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"welcomebutton\s+([^|]+)\|\s*(https?://\S+)$", outgoing=True))
    async def set_welcome_button(event):
        if not event.is_group:
            return await event.reply("💬 <b>Group mein use karo.</b>", parse_mode="html")
        if not await is_admin(event.chat_id):
            return await event.reply("⛔ <b>Admin-only.</b>", parse_mode="html")
        label = event.pattern_match.group(1).strip()[:40]
        url = event.pattern_match.group(2).strip()
        cfg = await welcome.find_one({"uid": uid, "chat_id": int(event.chat_id)}) or {}
        if len(cfg.get("buttons", [])) >= 4:
            return await event.reply("⚠️ <b>Maximum 4 welcome buttons allowed.</b> Clear existing buttons to replace them.", parse_mode="html")
        await welcome.update_one(
            {"uid": uid, "chat_id": int(event.chat_id)},
            {"$push": {"buttons": {"label": label, "url": url}}},
            upsert=True,
        )
        await event.reply("🔗 <b>Welcome URL button added!</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"welcomebuttonclear$", outgoing=True))
    async def clear_welcome_buttons(event):
        if not event.is_group or not await is_admin(event.chat_id):
            return await event.reply("⛔ <b>Group admin-only.</b>", parse_mode="html")
        await welcome.update_one({"uid": uid, "chat_id": int(event.chat_id)}, {"$set": {"buttons": []}}, upsert=True)
        await event.reply("🧹 <b>Welcome buttons cleared.</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=r"^" + p + r"welcomepicture$", outgoing=True))
    async def set_welcome_picture(event):
        if not event.is_group or not await is_admin(event.chat_id):
            return await event.reply("⛔ <b>Group admin-only.</b>", parse_mode="html")
        reply = await event.get_reply_message()
        if not reply or not reply.photo:
            return await event.reply("🖼 <b>Photo par reply karke</b> <code>%swelcomepicture</code> bhejo." % client.prefix, parse_mode="html")
        raw = await client.download_media(reply, file=bytes)
        if not raw:
            return await event.reply("❌ <b>Photo download nahi hui.</b>", parse_mode="html")
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((1600, 900))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85, optimize=True)
        if buf.tell() > 1_500_000:
            im.thumbnail((1200, 675))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=78, optimize=True)
        await welcome.update_one({"uid": uid, "chat_id": int(event.chat_id)}, {"$set": {"background": buf.getvalue()}}, upsert=True)
        await event.reply("🖼 <b>Welcome background saved!</b> Member profile photo and name will be overlaid on it.", parse_mode="html")

    @client.on(events.CallbackQuery(pattern=rb"^zyrawelcome:(toggle|preview|test|reset):(-?\d+)$"))
    async def welcome_panel_action(event):
        if event.sender_id != uid:
            return await event.answer("Only the connected account owner can change settings.", alert=True)
        action, raw_chat = event.data.decode().split(":")[1:]
        chat_id = int(raw_chat)
        if not await is_admin(chat_id):
            return await event.answer("Group admin permission required.", alert=True)
        if action == "toggle":
            cfg = await welcome.find_one({"uid": uid, "chat_id": chat_id}) or {}
            new_value = not cfg.get("enabled", True)
            await welcome.update_one({"uid": uid, "chat_id": chat_id}, {"$set": {"enabled": new_value}}, upsert=True)
            await event.answer("Welcome " + ("enabled" if new_value else "disabled"))
            await event.edit("💜 Welcome system is now <b>%s</b>." % ("ON" if new_value else "OFF"), parse_mode="html")
        elif action == "reset":
            await welcome.update_one(
                {"uid": uid, "chat_id": chat_id},
                {"$set": {"enabled": True, "text": "Welcome {first_name} to {group_name}! 💜", "buttons": []},
                 "$unset": {"background": ""}},
                upsert=True,
            )
            await event.answer("Settings reset")
            await event.edit("🔄 Welcome settings reset to defaults. Welcome is ON.")
        elif action in ("preview", "test"):
            cfg = await welcome.find_one({"uid": uid, "chat_id": chat_id}) or {}
            me = await client.get_me()
            # Preview is allowed even when welcome is disabled; test follows the real enabled state.
            if action == "preview":
                preview_cfg = dict(cfg)
                preview_cfg["enabled"] = True
                await send_welcome(chat_id, me, preview_cfg)
                await event.answer("👁️ Preview sent to group.")
            else:
                sent = await send_welcome(chat_id, me, cfg)
                await event.answer("🧪 Test welcome sent." if sent else "Welcome is disabled.", alert=not sent)
