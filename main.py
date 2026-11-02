import asyncio, logging, os, time

from aiohttp import web
from telethon import TelegramClient, events, Button, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError,
    FloodWaitError, PhoneNumberInvalidError, PasswordHashInvalidError,
)

import db, crypto
from manager import manager

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", 8080))
MAX_USERS = int(os.environ.get("MAX_USERS", 12))
OWNER_URL = os.environ.get("OWNER_URL", "https://t.me/Sakshamvenus")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/Sakshamabout_bot")
ADD_TO_GROUP_URL = os.environ.get("ADD_TO_GROUP_URL", "https://t.me/?startgroup=true")
START_STICKER_ID = os.environ.get("START_STICKER_ID", "").strip()
WELCOME_IMAGE = os.path.join(os.path.dirname(__file__), "assets", "zyra_welcome.png")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

bot = TelegramClient("master", API_ID, API_HASH)
states = {}


async def health(request):
    return web.Response(text="alive users=%s" % len(manager.clients))


async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("listening on %s", PORT)


WELCOME_TEXT = (
    "<b>✦ 𝐙𝐘𝐑𝐀 𝐔𝐒𝐄𝐑𝐁𝐎𝐓 ✦</b>\n"
    "<i>Personal Telegram workspace</i>\n\n"
    "╭─── ⟡ <b>WELCOME</b> ⟡ ───╮\n"
    "│  Your tools. Your settings. Your control.\n"
    "╰────────────────────╯\n\n"
    "▸ Add your own Telegram account to get started.\n"
    "▸ Manage commands and plugins from one place.\n"
    "▸ Use /help to explore available controls.\n\n"
    "<i>Keep your OTP and 2-step verification password private. "
    "Only connect an account you own.</i>"
)

HELP_TEXT = (
    "<b>✦ 𝐙𝐘𝐑𝐀 • 𝐇𝐄𝐋𝐏 𝐂𝐄𝐍𝐓𝐄𝐑 ✦</b>\n"
    "<i>Your Telegram workspace, neatly organized.</i>\n\n"
    "Choose a section below to explore commands.\n\n"
    "<b>ACCOUNT</b>\n"
    "<code>/login</code> · connect an account\n"
    "<code>/status</code> · connection status\n"
    "<code>/logout</code> · disconnect account\n"
    "<code>/prefix .</code> · set command prefix\n\n"
    "<b>USERBOT COMMANDS</b>\n"
    "Use your prefix (default <code>.</code>) in Telegram.\n"
    "<code>.help</code> · full userbot command list\n"
    "<code>.plugins</code> is available in the bot menu as <code>/plugins</code>.\n\n"
    "<i>Tap a category below for examples and usage.</i>"
)

HELP_SECTIONS = {
    b"help_account": (
        "<b>♙ ACCOUNT & SETTINGS</b>\n\n"
        "<code>/start</code> — welcome menu\n"
        "<code>/login</code> — connect your own Telegram account\n"
        "<code>/status</code> — show saved account and online status\n"
        "<code>/logout</code> — disconnect and remove saved session\n"
        "<code>/prefix .</code> — change userbot command prefix\n"
        "<code>/plugins</code> — enable/disable installed plugins\n"
        "<code>/cancel</code> — cancel an in-progress login\n\n"
        "<i>Only connect accounts you own. Keep OTP and 2-step password private.</i>"
    ),
    b"help_tools": (
        "<b>✧ TEXT & UTILITY TOOLS</b>\n\n"
        "<code>.ping</code> — check response speed\n"
        "<code>.alive</code> — show account status\n"
        "<code>.echo hello</code> — repeat text\n"
        "<code>.calc 12*4</code> — basic maths\n"
        "<code>.reverse hello</code> — reverse text\n"
        "<code>.clap hello world</code> — clap between words\n"
        "<code>.emojify hello</code> — add emojis\n"
        "<code>.spoiler secret</code> — format spoiler text\n"
        "<code>.type hello</code> — typewriter effect\n\n"
        "<i>Replace the dot with your configured prefix if you changed it.</i>"
    ),
    b"help_social": (
        "<b>♡ AFK, NOTES & AUTO-REPLIES</b>\n\n"
        "<code>.afk studying</code> — set AFK status\n"
        "<code>.unafk</code> — clear AFK status\n"
        "<code>.note name | text</code> — save a note\n"
        "<code>.getnote name</code> — read a note\n"
        "<code>.delnote name</code> — delete a note\n"
        "<code>.notes</code> — list saved notes\n\n"
        "<code>.autoreply hi | hello</code> — add an auto-reply\n"
        "<code>.delreply hi</code> — remove an auto-reply\n"
        "<code>.replies</code> — list auto-replies\n"
        "<code>.filter word | reply</code> — add a text filter\n"
        "<code>.stop word</code> — remove a filter\n"
        "<code>.filters</code> — list filters\n\n"
        "<i>Auto-reply/filter rules run while the userbot client is online.</i>"
    ),
    b"help_admin": (
        "<b>⚒ GROUP ADMIN TOOLS</b>\n\n"
        "Reply to a user's message, then use: <code>.ban</code>, <code>.unban</code>, "
        "<code>.mute</code>, <code>.unmute</code>, <code>.kick</code>, <code>.del</code>.\n\n"
        "<code>.pin</code> — pin replied message\n"
        "<code>.unpin</code> — unpin latest message\n"
        "<code>.purge 20</code> — delete up to 100 recent messages\n"
        "<code>.admins</code> — list admins\n"
        "<code>.id</code> — show chat/user ID\n"
        "<code>.adminhelp</code> — show admin usage\n\n"
        "<i>Telegram must allow your account to perform the action. Use moderation tools responsibly.</i>"
    ),
    b"help_ai": (
        "<b>✦ AI & PLUGINS</b>\n\n"
        "<code>.ai your question</code> — ask the configured AI provider\n"
        "<code>/plugins</code> — view plugin toggles in the bot chat\n\n"
        "AI works only when its provider key, model and API base URL are configured correctly.\n"
        "<i>Plugin changes may restart your connected userbot client.</i>"
    ),
}

HELP = HELP_TEXT


def start_buttons():
    return [
        [Button.url("➕  ADD TO GROUP", ADD_TO_GROUP_URL)],
        [Button.inline("✦  ADD ACCOUNT", b"login")],
        [Button.inline("⌘  HELP CENTER", b"help"), Button.url("♡  SUPPORT", SUPPORT_URL)],
        [Button.url("♛  OWNER", OWNER_URL)],
    ]


def help_buttons():
    return [
        [Button.inline("♙ Account & Settings", b"help_account")],
        [Button.inline("✧ Text & Utilities", b"help_tools"), Button.inline("♡ Social Tools", b"help_social")],
        [Button.inline("⚒ Admin Tools", b"help_admin"), Button.inline("✦ AI & Plugins", b"help_ai")],
        [Button.inline("↩ Back to Start", b"back_start")],
    ]


def section_buttons():
    return [
        [Button.inline("⌂ Help Center", b"help")],
        [Button.inline("↩ Back to Start", b"back_start")],
    ]


async def send_start_menu(chat_id, reply_to=None):
    # Prefer a sticker message saved through this bot; this works with Telethon
    # and survives redeploys when MongoDB is configured.
    try:
        saved = await db.settings.find_one({"_id": "start_sticker"})
        if saved:
            source = await bot.get_messages(saved["chat_id"], ids=saved["message_id"])
            if source and source.media:
                await bot.send_file(chat_id, source, reply_to=reply_to)
        elif START_STICKER_ID:
            # Kept as a fallback for compatible Telethon media references.
            await bot.send_file(chat_id, START_STICKER_ID, reply_to=reply_to)
    except Exception as ex:
        log.warning("start sticker could not be sent; send a sticker directly to this bot to save it: %s", ex)
    try:
        await bot.send_file(
            chat_id,
            WELCOME_IMAGE,
            caption=WELCOME_TEXT,
            buttons=start_buttons(),
            parse_mode="html",
            reply_to=reply_to,
        )
    except Exception as ex:
        log.warning("welcome image could not be sent; using text fallback: %s", ex)
        await bot.send_message(chat_id, WELCOME_TEXT, buttons=start_buttons(), parse_mode="html", reply_to=reply_to)


@bot.on(events.NewMessage(pattern=r"^/start$"))
async def cmd_start(e):
    try:
        await bot(functions.messages.SendReactionRequest(
            peer=e.peer_id,
            msg_id=e.id,
            reaction=[types.ReactionEmoji(emoticon="👋")],
        ))
    except Exception as ex:
        log.warning("Start reaction failed (Telegram may not allow this chat/reaction): %s", ex)
    await send_start_menu(e.chat_id)


@bot.on(events.NewMessage(func=lambda e: e.is_private and bool(e.message and e.message.document) and any(isinstance(a, types.DocumentAttributeSticker) for a in e.message.document.attributes)))
async def sticker_id_helper(e):
    # Save the source message reference in MongoDB; Telethon uses MTProto media,
    # not Bot API file_id strings from third-party ID bots.
    try:
        await db.settings.update_one(
            {"_id": "start_sticker"},
            {"$set": {"chat_id": e.chat_id, "message_id": e.id}},
            upsert=True,
        )
        await e.reply(
            "🩵 <b>Zyra welcome sticker saved!</b>\n"
            "Ab /start par ye sticker welcome image se pehle aayega.\n"
            "MongoDB enabled rehna chahiye taaki setting redeploy ke baad bhi rahe.",
            parse_mode="html",
        )
    except Exception as ex:
        log.exception("Could not save welcome sticker")
        await e.reply("Sticker save nahi hua. Render logs check karo.")


@bot.on(events.CallbackQuery(data=b"help"))
async def cb_help(e):
    await e.answer()
    try:
        await e.delete()
    except Exception as ex:
        log.warning("Could not delete previous menu before help: %s", ex)
    await bot.send_message(e.chat_id, HELP_TEXT, parse_mode="html", buttons=help_buttons())


@bot.on(events.CallbackQuery(pattern=rb"^help_(account|tools|social|admin|ai)$"))
async def cb_help_section(e):
    await e.answer()
    key = e.data
    text = HELP_SECTIONS.get(key)
    if not text:
        return
    try:
        await e.delete()
    except Exception as ex:
        log.warning("Could not delete previous help menu: %s", ex)
    await bot.send_message(e.chat_id, text, parse_mode="html", buttons=section_buttons())


@bot.on(events.CallbackQuery(data=b"back_start"))
async def cb_back_start(e):
    await e.answer()
    try:
        await e.delete()
    except Exception as ex:
        log.warning("Could not delete help message before returning to start: %s", ex)
    await send_start_menu(e.chat_id)


async def start_login(uid, event):
    """Start the phone-number login flow for the user who pressed Add Account."""
    if not event.is_private:
        await event.respond("🔒 Account login sirf bot ke private chat mein karein.")
        return

    existing = await db.users.find_one({"_id": uid})
    if existing:
        await event.respond(
            "ℹ️ Aapka account pehle se connected hai.\n"
            "Status ke liye /status use karein. Naya account connect karna ho "
            "to pehle /logout karein, phir Add Account dabayein."
        )
        return

    try:
        count = await db.users.count_documents({})
        if count >= MAX_USERS:
            await event.respond("Abhi account limit full hai. Baad mein try karein.")
            return
    except Exception:
        log.exception("Could not check account limit")

    states[uid] = {"step": "phone"}
    prompt = (
        "<b>➕ ADD TELEGRAM ACCOUNT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Apne Telegram account ka phone number international format mein bhejein.\n"
        "Example: <code>+91XXXXXXXXXX</code>\n\n"
        "<i>Login ke liye Telegram OTP aur agar enabled ho to 2-step password lagega.</i>\n"
        "🔐 Sirf apna account connect karein. OTP/password kisi ke saath share na karein.\n\n"
        "Cancel karne ke liye /cancel bhejein."
    )
    await bot.send_message(event.chat_id, prompt, parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/cancel$"))
async def cmd_cancel_login(e):
    uid = e.sender_id
    st = states.pop(uid, None)
    if st and st.get("client"):
        try:
            await st["client"].disconnect()
        except Exception:
            log.exception("Could not disconnect cancelled login client")
    await e.reply("Login process cancel kar diya gaya hai.")


@bot.on(events.CallbackQuery(data=b"login"))
async def cb_login(e):
    await e.answer()
    await start_login(e.sender_id, e)




@bot.on(events.NewMessage(pattern=r"^/login$"))
async def cmd_login(e):
    await start_login(e.sender_id, e)


@bot.on(events.NewMessage(pattern=r"^/help$"))
async def cmd_help(e):
    await bot.send_message(e.chat_id, HELP_TEXT, parse_mode="html", buttons=help_buttons())


@bot.on(events.NewMessage(pattern=r"^/logout$"))
async def cmd_logout(e):
    uid = e.sender_id
    await manager.kill(uid)
    await db.users.delete_one({"_id": uid})
    states.pop(uid, None)
    await e.reply("Logged out, session delete ho gaya.")


@bot.on(events.NewMessage(pattern=r"^/status$"))
async def cmd_status(e):
    uid = e.sender_id
    doc = await db.users.find_one({"_id": uid})
    if not doc:
        return await e.reply("Koi account nahi. /login")
    live = uid in manager.clients
    await e.reply(
        "Account: <code>%s</code>\nPrefix: <code>%s</code>\nState: %s\nDisabled: %s"
        % (
            doc.get("name", "?"),
            doc.get("prefix", "."),
            "online" if live else "offline",
            ", ".join(doc.get("disabled", [])) or "none",
        )
    )


@bot.on(events.NewMessage(pattern=r"^/prefix(?:\s+(\S+))?$"))
async def cmd_prefix(e):
    uid = e.sender_id
    new = e.pattern_match.group(1)
    if not new:
        return await e.reply("Usage: <code>/prefix .</code>")
    await db.users.update_one({"_id": uid}, {"$set": {"prefix": new}})
    c = manager.clients.get(uid)
    if c:
        c.prefix = new
    await e.reply("Prefix set: <code>%s</code>" % new)


@bot.on(events.NewMessage(pattern=r"^/plugins$"))
async def cmd_plugins(e):
    import pkgutil, plugins as pkg
    uid = e.sender_id
    doc = await db.users.find_one({"_id": uid})
    if not doc:
        return await e.reply("Pehle /login karo.")
    disabled = set(doc.get("disabled", []))
    btns = []
    for m in pkgutil.iter_modules(pkg.__path__):
        label = ("OFF" if m.name in disabled else "ON") + " · " + m.name
        btns.append([Button.inline(label, ("tg:" + m.name).encode())])
    await e.reply("Plugin toggle (restart ke baad apply hoga):", buttons=btns)


@bot.on(events.CallbackQuery(pattern=rb"^tg:(.+)$"))
async def cb_toggle(e):
    name = e.pattern_match.group(1).decode()
    uid = e.sender_id
    doc = await db.users.find_one({"_id": uid})
    if not doc:
        return await e.answer("Login karo", alert=True)
    disabled = set(doc.get("disabled", []))
    disabled.symmetric_difference_update({name})
    await db.users.update_one({"_id": uid}, {"$set": {"disabled": list(disabled)}})
    # Apply plugin changes immediately to this user's running client.
    await manager.kill(uid)
    fresh = await db.users.find_one({"_id": uid})
    if fresh and fresh.get("enabled", True) and not fresh.get("dead", False):
        await manager.spawn(fresh)
    await e.answer(name + ": " + ("OFF" if name in disabled else "ON"))


@bot.on(events.NewMessage())
async def router(e):
    uid = e.sender_id
    st = states.get(uid)
    if not st or not e.raw_text or e.raw_text.startswith("/"):
        return

    text = e.raw_text.strip()

    if st["step"] == "phone":
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            sent = await client.send_code_request(text)
        except PhoneNumberInvalidError:
            await client.disconnect()
            return await e.reply("Invalid number. Dobara bhejo.")
        except FloodWaitError as ex:
            await client.disconnect()
            return await e.reply("FloodWait %ss. Baad me try karo." % ex.seconds)
        except Exception as ex:
            await client.disconnect()
            return await e.reply("<code>%s</code>" % ex)

        st.update(step="code", phone=text, client=client, hash=sent.phone_code_hash)
        await e.reply("OTP bhejo. Format: <code>1 2 3 4 5</code> ya <code>12345</code>")

    elif st["step"] == "code":
        client = st["client"]
        code = text.replace(" ", "")
        try:
            await client.sign_in(st["phone"], code, phone_code_hash=st["hash"])
        except SessionPasswordNeededError:
            st["step"] = "2fa"
            return await e.reply("2FA password bhejo.")
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as ex:
            return await e.reply(type(ex).__name__ + " — dobara /login karo")
        except Exception as ex:
            return await e.reply("<code>%s</code>" % ex)
        await finish_login(uid, e, client, st["phone"])

    elif st["step"] == "2fa":
        client = st["client"]
        try:
            await client.sign_in(password=text)
        except PasswordHashInvalidError:
            return await e.reply("Password galat. Dobara bhejo.")
        await finish_login(uid, e, client, st["phone"])


async def finish_login(uid, e, client, phone):
    try:
        await e.reply("Saving...")
        me = await client.get_me()
        session = client.session.save()
        await db.users.update_one(
            {"_id": uid},
            {"$set": {
                "phone": phone,
                "name": me.first_name or str(me.id),
                "session": crypto.enc(session),
                "prefix": ".",
                "enabled": True,
                "dead": False,
                "disabled": [],
            }},
            upsert=True,
        )
        await client.disconnect()
        doc = await db.users.find_one({"_id": uid})
        await manager.spawn(doc)
        states.pop(uid, None)
        await e.reply(
            "✅ Login ho gaya: <b>%s</b>. Prefix <code>.</code> — <code>.ping</code> try karo."
            % me.first_name
        )
    except Exception as ex:
        log.exception("finish_login")
        await e.reply("<code>%s</code>" % ex)


async def main():
    await start_web()
    await bot.start(bot_token=BOT_TOKEN)
    await manager.boot_all()
    monitor_task = asyncio.create_task(manager.monitor_connections(), name="client-reconnect-monitor")
    log.info("ready")
    try:
        await bot.run_until_disconnected()
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
