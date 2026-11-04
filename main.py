import asyncio, logging, os, time, random, re, ast, html, tempfile
import aiohttp

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
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or 0)
LOGGER_GROUP_ID = int(os.environ.get("LOGGER_GROUP_ID", "0") or 0)
WELCOME_IMAGE = os.path.join(os.path.dirname(__file__), "assets", "zyra_welcome.png")
WELCOME_ANIMATION = os.environ.get("WELCOME_ANIMATION", os.path.join(os.path.dirname(__file__), "assets", "zyra_welcome.mp4")).strip()

# Rotating start video URLs adapted from the reference KittuBot repository.
START_VIDEO_URLS = [
    "https://yukiapi.site/file/6CXCn2De",
    "https://yukiapi.site/file/YWwD9Qr8",
    "https://yukiapi.site/file/rsCNQf0j",
    "https://yukiapi.site/file/dWFtIZny",
    "https://yukiapi.site/file/eYtZuZwz",
    "https://yukiapi.site/file/euiiZogt",
    "https://yukiapi.site/file/UcidJrAQ",
    "https://yukiapi.site/file/AtKzDFZU",
    "https://yukiapi.site/file/nGA7YMtQ",
    "https://yukiapi.site/file/aQSUKqZk",
    "https://yukiapi.site/file/ns7QmFhQ",
    "https://yukiapi.site/file/tZCMxz2a",
]

# Auto-sync the START_IMG_URL list from KITTUBOT's GitHub config.
# The built-in URLs above remain a fallback if GitHub is unavailable.
KITTU_CONFIG_URL = os.environ.get(
    "KITTU_CONFIG_URL",
    "https://raw.githubusercontent.com/sakshamvibesyt/Sem_KITTUBOT/main/KITTUBOT/config.py",
).strip()
VIDEO_URL_REFRESH_SECONDS = max(
    300, int(os.environ.get("VIDEO_URL_REFRESH_SECONDS", "900") or 900)
)


async def refresh_start_video_urls():
    global START_VIDEO_URLS
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(KITTU_CONFIG_URL) as response:
                response.raise_for_status()
                source = await response.text()
        match = re.search(
            r"START_IMG_URL\s*:[^=]*=\s*(\[[\s\S]*?\])",
            source,
        )
        if not match:
            raise ValueError("START_IMG_URL list was not found in KITTUBOT config")
        urls = ast.literal_eval(match.group(1))
        urls = [
            url.strip() for url in urls
            if isinstance(url, str) and url.strip().startswith(("https://", "http://"))
        ]
        if not urls:
            raise ValueError("KITTUBOT config returned an empty video URL list")
        START_VIDEO_URLS = urls
        log.info("Synced %s start video URLs from KITTUBOT GitHub config", len(urls))
    except Exception as ex:
        log.warning(
            "Could not refresh KITTUBOT video URLs; keeping %s fallback URLs: %s",
            len(START_VIDEO_URLS), ex,
        )


async def refresh_video_urls_periodically():
    while True:
        await asyncio.sleep(VIDEO_URL_REFRESH_SECONDS)
        await refresh_start_video_urls()


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

bot = TelegramClient("master", API_ID, API_HASH)
states = {}

# Control-panel access is separate from the connected user accounts.
# OWNER_ID must be set explicitly in Render environment variables.
admins = db.db.zyra_panel_admins
bot_start_users = db.db.zyra_bot_start_users


async def send_logger_log(text):
    """Send a formatted event to the configured logger group; logging must never break bot features."""
    if not LOGGER_GROUP_ID:
        return
    try:
        await bot.send_message(LOGGER_GROUP_ID, text, parse_mode="html", link_preview=False)
    except Exception as ex:
        log.warning("Could not send logger-group event: %s", ex)


def display_name(doc):
    return html.escape(str(doc.get("name") or doc.get("first_name") or doc.get("_id") or "Unknown"))

async def is_owner(uid):
    return bool(OWNER_ID and uid == OWNER_ID)

async def is_panel_admin(uid):
    if await is_owner(uid):
        return True
    return bool(await admins.find_one({"_id": int(uid)}))

async def require_panel_access(event):
    if not await is_panel_admin(event.sender_id):
        await event.reply("🔒 <b>Zyra access denied.</b> Sirf owner ya approved admin ye command use kar sakta hai.", parse_mode="html")
        return False
    return True


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


def build_welcome_text(user_name="there"):
    """Create a short personalized preview with Telegram's expandable details."""
    safe_name = html.escape((user_name or "there").strip())
    return (
        f"<b>✦ 𝐙𝐘𝐑𝐀 𝐔𝐒𝐄𝐑𝐁𝐎𝐓 ✦</b>\n"
        f"💜 <b>Welcome, {safe_name}!</b>\n"
        "<i>Your personal Telegram workspace is ready.</i>\n\n"
        "<blockquote expandable>"
        "╭─── ⟡ <b>QUICK START</b> ⟡ ───╮\n"
        "✦ Add your Telegram account using <b>ADD ACCOUNT</b>.\n"
        "✦ Open <b>HELP CENTER</b> to explore commands and tools.\n"
        "✦ Use the buttons below to navigate Zyra.\n"
        "╰────────────────────╯\n\n"
        "<b>Features</b>\n"
        "▸ Account & session management\n"
        "▸ Text utilities and personal tools\n"
        "▸ Help, settings and plugin controls\n\n"
        "<i>Security note: never share your Telegram login code or 2-step verification password. Connect only accounts you own.</i>"
        "</blockquote>"
    )

HELP_TEXT = (
    "<b>✦ 𝐙𝐘𝐑𝐀 • 𝐇𝐄𝐋𝐏 𝐂𝐄𝐍𝐓𝐄𝐑 ✦</b>\n"
    "<i>Your Telegram workspace, neatly organized.</i>\n\n"
    "Choose a section below to explore commands.\n\n"
    "<b>ACCOUNT</b>\n"
    "<code>/panel</code> · open control panel\n"
    "<code>/login</code> · connect an account\n"
    "<code>/status</code> · connection status\n"
    "<code>/logout</code> · disconnect account\n"
    "<code>/prefix .</code> · set command prefix\n\n"
    "<b>USERBOT COMMANDS</b>\n"
    "Use your prefix (default <code>.</code>) in Telegram.\n"
    "<code>.help</code> · full userbot command list\n"
    "<code>.plugins</code> is available in the bot menu as <code>/plugins</code>.\n\n"
    "<i>Tap a category below for examples and usage.</i>\n\n"
    "<b>OWNER PANEL</b>\n<code>/addadmin user_id</code> · add trusted admin (owner only)\n"
    "<code>/removeadmin user_id</code> · remove trusted admin (owner only)\n"
    "<code>/admins</code> · list panel admins\n"
    "<code>/myid</code> · show your Telegram numeric ID"
)

HELP_SECTIONS = {
    b"help_account": (
        "<b>♙ ACCOUNT & SETTINGS</b>\n\n"
        "<code>/start</code> — welcome menu\n"
        "<code>/panel</code> — open control panel (owner/admin)\n"
        "<code>/login</code> — connect your own Telegram account\n"
        "<code>/status</code> — show saved account and online status\n"
        "<code>/logout</code> — disconnect and remove saved session\n"
        "<code>/prefix .</code> — change userbot command prefix\n"
        "<code>/plugins</code> — enable/disable installed plugins\n"
        "<code>/cancel</code> — cancel an in-progress login\n"
        "<code>/addadmin user_id</code> — owner-only: add trusted panel admin\n"
        "<code>/removeadmin user_id</code> — owner-only: remove panel admin\n"
        "<code>/admins</code> — list panel admins\n\n"
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
    # Personalize the visible welcome line with the Telegram user's first name.
    try:
        user = await bot.get_entity(chat_id)
        user_name = getattr(user, "first_name", None) or getattr(user, "title", None) or "there"
    except Exception:
        user_name = "there"
    welcome_text = build_welcome_text(user_name)

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
    # Prefer the rotating KITTUBOT media as the actual welcome media, not as a
    # separate link-preview message followed by the old static image.
    random_video = random.choice(START_VIDEO_URLS) if START_VIDEO_URLS else ""
    if random_video:
        temp_path = None
        try:
            timeout = aiohttp.ClientTimeout(total=25, connect=8, sock_read=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(random_video, allow_redirects=True) as response:
                    response.raise_for_status()
                    content_type = (response.headers.get("Content-Type") or "").lower()
                    length = int(response.headers.get("Content-Length") or 0)
                    if length > 45 * 1024 * 1024:
                        raise ValueError("KITTUBOT media is larger than 45 MB")
                    body = await response.read()
            # MP4 files normally contain the ftyp signature near the beginning.
            if not ("video/" in content_type or "octet-stream" in content_type or b"ftyp" in body[:64]):
                raise ValueError("KITTUBOT URL did not return a direct video file")
            if len(body) > 45 * 1024 * 1024:
                raise ValueError("KITTUBOT media is larger than 45 MB")
            if len(body) < 1024:
                raise ValueError("KITTUBOT media response was too small")
            with tempfile.NamedTemporaryFile(prefix="zyra_start_", suffix=".mp4", delete=False) as handle:
                handle.write(body)
                temp_path = handle.name
            await bot.send_file(
                chat_id, temp_path, caption=welcome_text, buttons=start_buttons(),
                parse_mode="html", reply_to=reply_to, supports_streaming=True,
            )
            return
        except Exception as ex:
            log.warning("Could not send KITTUBOT video as welcome media; trying preview fallback: %s", ex)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        # If the URL is a preview page rather than a direct media file, keep the
        # KITTUBOT preview and the menu in one message; do not send the old image too.
        try:
            video_caption = f'<a href="{html.escape(random_video, quote=True)}">&#8203;</a>' + welcome_text
            await bot.send_message(
                chat_id, video_caption, buttons=start_buttons(), parse_mode="html",
                link_preview=True, reply_to=reply_to,
            )
            return
        except Exception as ex:
            log.warning("KITTUBOT preview fallback failed: %s", ex)

    media_path = WELCOME_ANIMATION if WELCOME_ANIMATION and os.path.isfile(WELCOME_ANIMATION) else WELCOME_IMAGE
    try:
        await bot.send_file(
            chat_id,
            media_path,
            caption=welcome_text,
            buttons=start_buttons(),
            parse_mode="html",
            reply_to=reply_to,
        )
    except Exception as ex:
        log.warning("welcome media could not be sent; using text fallback: %s", ex)
        await bot.send_message(chat_id, welcome_text, buttons=start_buttons(), parse_mode="html", reply_to=reply_to)




@bot.on(events.NewMessage(pattern=r"^/start(?:@\w+)?(?:\s+.*)?$"))
async def cmd_start(e):
    """Show the welcome menu when someone sends /start."""
    log.info("/start received user_id=%s", e.sender_id)
    # Log only the first /start from each Telegram user, avoiding repeated spam.
    try:
        sender = await e.get_sender()
        first_name = (getattr(sender, "first_name", None) or "Telegram user").strip()
        username = getattr(sender, "username", None)
        start_record = await bot_start_users.find_one({"_id": int(e.sender_id)})
        if not start_record:
            await bot_start_users.update_one(
                {"_id": int(e.sender_id)},
                {"$set": {"name": first_name, "username": username}},
                upsert=True,
            )
            username_line = f"\n♧ Username: @{html.escape(username)}" if username else "\n♧ Username: <i>not set</i>"
            total_started = await bot_start_users.count_documents({})
            await send_logger_log(
                "🪄 <b>NEW BOT USER</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👤 Name: <b>{html.escape(first_name)}</b>\n"
                f"🆔 ID: <code>{e.sender_id}</code>"
                f"{username_line}\n"
                f"📊 First-time users: <b>{total_started}</b>\n"
                "✨ <i>Zyra just got a new visitor!</i>"
            )
    except Exception as ex:
        log.warning("Could not record /start event: %s", ex)
    # A reaction is optional; failure must never prevent the welcome menu.
    try:
        await bot(functions.messages.SendReactionRequest(
            peer=e.peer_id,
            msg_id=e.id,
            reaction=[types.ReactionEmoji(emoticon="❤️")],
        ))
    except Exception as ex:
        log.warning("Start reaction failed; continuing to welcome menu: %s", ex)
    await send_start_menu(e.chat_id)

def is_welcome_media_message(event):
    """Match media sent privately by the configured owner for welcome-sticker saving."""
    return bool(
        OWNER_ID
        and event.is_private
        and event.sender_id == OWNER_ID
        and event.media
        and not getattr(event, "via_bot_id", None)
    )


@bot.on(events.NewMessage(func=is_welcome_media_message))
async def sticker_id_helper(e):
    if not await require_panel_access(e):
        return
    # Save the source message reference in MongoDB; Telethon uses MTProto media,
    # not Bot API file_id strings from third-party ID bots.
    try:
        await db.settings.update_one(
            {"_id": "start_sticker"},
            {"$set": {"chat_id": e.chat_id, "message_id": e.id}},
            upsert=True,
        )
        await e.reply(
            "🩵 <b>Zyra welcome media saved!</b>\n"
            "Ab /start par ye sticker/GIF/video welcome image se pehle aayega.\n"
            "Tip: animated welcome ke liye GIF ya short MP4 bhejo. MongoDB setting ko redeploy ke baad bhi save rakhega.",
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
    if not await require_panel_access(e):
        return
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
    if not await is_panel_admin(e.sender_id):
        return await e.answer("Owner/admin access required", alert=True)
    await e.answer()
    await start_login(e.sender_id, e)




@bot.on(events.NewMessage(pattern=r"^/login$"))
async def cmd_login(e):
    if not await require_panel_access(e):
        return
    await start_login(e.sender_id, e)


@bot.on(events.NewMessage(pattern=r"^/panel$"))
async def cmd_panel(e):
    if not await require_panel_access(e):
        return
    if not e.is_private:
        return await e.reply("🔒 /panel ko bot ke private chat mein use karein.")
    await send_start_menu(e.chat_id)


@bot.on(events.NewMessage(pattern=r"^/help$"))
async def cmd_help(e):
    await bot.send_message(e.chat_id, HELP_TEXT, parse_mode="html", buttons=help_buttons())


@bot.on(events.NewMessage(pattern=r"^/logout$"))
async def cmd_logout(e):
    if not await require_panel_access(e):
        return
    uid = e.sender_id
    await manager.kill(uid)
    await db.users.delete_one({"_id": uid})
    states.pop(uid, None)
    await e.reply("Logged out, session delete ho gaya.")


@bot.on(events.NewMessage(pattern=r"^/status$"))
async def cmd_status(e):
    if not await require_panel_access(e):
        return
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
    if not await require_panel_access(e):
        return
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
    if not await require_panel_access(e):
        return
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
    if not await is_panel_admin(e.sender_id):
        return await e.answer("Owner/admin access required", alert=True)
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


@bot.on(events.NewMessage(pattern=r"^/myid$"))
async def cmd_myid(e):
    await e.reply("Your Telegram user ID: <code>%s</code>" % e.sender_id, parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/addadmin\s+(\d+)$"))
async def cmd_addadmin(e):
    if not await is_owner(e.sender_id):
        return await e.reply("🔒 Sirf configured owner admin add kar sakta hai.")
    target = int(e.pattern_match.group(1))
    if OWNER_ID and target == OWNER_ID:
        return await e.reply("Owner already has full access.")
    await admins.update_one({"_id": target}, {"$set": {"added_by": e.sender_id, "created_at": int(time.time())}}, upsert=True)
    log.info("panel admin added by owner_id=%s target_id=%s", e.sender_id, target)
    await e.reply("✅ Trusted admin add ho gaya: <code>%s</code>\nAb woh panel commands aur apne connected account ke tools use kar sakta hai." % target, parse_mode="html")


@bot.on(events.NewMessage(pattern=r"^/removeadmin\s+(\d+)$"))
async def cmd_removeadmin(e):
    if not await is_owner(e.sender_id):
        return await e.reply("🔒 Sirf configured owner admin remove kar sakta hai.")
    target = int(e.pattern_match.group(1))
    result = await admins.delete_one({"_id": target})
    log.info("panel admin removed by owner_id=%s target_id=%s", e.sender_id, target)
    await e.reply("✅ Admin remove kar diya." if result.deleted_count else "Ye ID admin list mein nahi thi.")


@bot.on(events.NewMessage(pattern=r"^/admins$"))
async def cmd_list_admins(e):
    if not await require_panel_access(e):
        return
    rows = await admins.find({}).to_list(length=100)
    lines = ["• <code>%s</code>" % row["_id"] for row in rows]
    if OWNER_ID:
        lines.insert(0, "• <code>%s</code> — OWNER" % OWNER_ID)
    await e.reply("<b>✦ ZYRA TRUSTED ADMINS</b>\n\n" + ("\n".join(lines) if lines else "No extra admins added."), parse_mode="html")


@bot.on(events.NewMessage())
async def router(e):
    uid = e.sender_id
    if not await is_panel_admin(uid):
        return
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
        previous_user = await db.users.find_one({"_id": uid})
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
        if not previous_user:
            login_total = await db.users.count_documents({})
            await send_logger_log(
                "🔐 <b>NEW ACCOUNT LOGIN</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👤 Account: <b>{html.escape(me.first_name or str(me.id))}</b>\n"
                f"🆔 Telegram ID: <code>{me.id}</code>\n"
                f"🧩 Added by user ID: <code>{uid}</code>\n"
                f"📊 Connected accounts: <b>{login_total}</b>\n"
                "✅ <i>Account saved and session started.</i>"
            )
        else:
            await send_logger_log(
                "♻️ <b>ACCOUNT SESSION REFRESHED</b>\n"
                f"👤 Account: <b>{html.escape(me.first_name or str(me.id))}</b>\n"
                f"🆔 Telegram ID: <code>{me.id}</code>\n"
                "✅ <i>Session refreshed successfully.</i>"
            )
        await e.reply(
            "✅ Login ho gaya: <b>%s</b>. Prefix <code>.</code> — <code>.ping</code> try karo."
            % me.first_name
        )
    except Exception as ex:
        log.exception("finish_login")
        await e.reply("<code>%s</code>" % ex)


async def main():
    await start_web()
    await refresh_start_video_urls()
    await bot.start(bot_token=BOT_TOKEN)
    await manager.boot_all()
    # Deployment summary plus one profile-status card per saved account.
    try:
        total_accounts = await db.users.count_documents({})
        online_accounts = len(manager.clients)
        total_bot_users = await bot_start_users.count_documents({})
        await send_logger_log(
            "🚀 <b>ZYRA USERBOT · DEPLOY ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💜 Status: <b>ONLINE</b>\n"
            f"👥 Saved accounts: <b>{total_accounts}</b>\n"
            f"🟢 Active clients: <b>{online_accounts}</b>\n"
            f"📨 Bot users recorded: <b>{total_bot_users}</b>\n"
            "⚡ <i>All saved profiles are being checked below.</i>"
        )
        async for account in db.users.find({}):
            uid = account.get("_id")
            is_online = uid in manager.clients
            status = "🟢 ONLINE" if is_online else "🟠 SAVED · NOT ACTIVE"
            await send_logger_log(
                "👤 <b>PROFILE LOADED</b>\n"
                f"✦ Name: <b>{display_name(account)}</b>\n"
                f"🆔 User ID: <code>{uid}</code>\n"
                f"📡 Status: <b>{status}</b>\n"
                "━━━━━━━━━━━━━━━━━━"
            )
    except Exception as ex:
        log.warning("Could not send deploy summary to logger group: %s", ex)
    monitor_task = asyncio.create_task(manager.monitor_connections(), name="client-reconnect-monitor")
    video_refresh_task = asyncio.create_task(
        refresh_video_urls_periodically(), name="kittu-video-url-refresh"
    )
    log.info("ready")
    try:
        await bot.run_until_disconnected()
    finally:
        monitor_task.cancel()
        video_refresh_task.cancel()
        for task in (monitor_task, video_refresh_task):
            try:
                await task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
