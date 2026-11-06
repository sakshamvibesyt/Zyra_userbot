import asyncio, logging, os, time, random, html
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
OWNER_URL = os.environ.get("OWNER_URL", "https://t.me/coderxsem")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/+5suOiNvkW-43YTc9")
ADD_TO_GROUP_URL = os.environ.get("ADD_TO_GROUP_URL", "https://t.me/?startgroup=true")
START_STICKER_ID = os.environ.get("START_STICKER_ID", "").strip()
START_STICKER_MESSAGE = None
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or 0)
LOGGER_GROUP_ID = int(os.environ.get("LOGGER_GROUP_ID", "0") or 0)
WELCOME_IMAGE = os.path.join(os.path.dirname(__file__), "assets", "zyra_welcome.png")
WELCOME_ANIMATION = os.environ.get("WELCOME_ANIMATION", os.path.join(os.path.dirname(__file__), "assets", "zyra_welcome.mp4")).strip()

# Direct MP4 URLs used for the /start welcome video rotation.
START_VIDEO_URLS = [
    "https://www.image2url.com/r2/default/videos/1793904409822-271da135-72b3-4664-b931-9da3a3edde92.mp4",
    "https://www.image2url.com/r2/default/videos/1793904536328-a3959414-4662-495a-aade-5eb8cdf7bf74.mp4",
    "https://www.image2url.com/r2/default/videos/1793904593839-c821c4a8-6be4-4fb7-95c4-5596519c0d4e.mp4",
    "https://www.image2url.com/r2/default/videos/1793904686803-50ec5d20-2ecc-4e04-be61-2a9645417052.mp4",
    "https://www.image2url.com/r2/default/videos/1793904805127-9653e795-19be-418f-b7fa-4395b6f74295.mp4",
]
START_VIDEO_BAG = []
START_ANIMATION_ENABLED = os.environ.get("START_ANIMATION_ENABLED", "false").lower() in ("1", "true", "yes")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

bot = TelegramClient("master", API_ID, API_HASH)
states = {}

admins = db.db.zyra_panel_admins
bot_start_users = db.db.zyra_bot_start_users


async def send_logger_log(text):
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
    safe_name = html.escape((user_name or "there").strip())
    return (
        f"<b>✦ 𝐙𝐘𝐑𝐀 𝐔𝐒𝐄𝐑𝐁𝐎𝐓 ✦</b>\n"
        f"💜 <b>Welcome, {safe_name}!</b>\n"
        "👑 Owner: <a href=\"https://t.me/coderxsem\">Saksham</a> · <code>@coderxsem</code>\n"
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


async def load_start_sticker_cache():
    global START_STICKER_MESSAGE
    try:
        saved = await db.settings.find_one({"_id": "start_sticker"})
        if saved:
            source = await bot.get_messages(saved["chat_id"], ids=saved["message_id"])
            if source and source.media:
                START_STICKER_MESSAGE = source
    except Exception as ex:
        log.warning("Could not preload start sticker: %s", ex)


def pick_welcome_video():
    """Choose a remote MP4 without repeating until the current URL cycle is used."""
    global START_VIDEO_BAG
    available = list(START_VIDEO_URLS)
    START_VIDEO_BAG = [url for url in START_VIDEO_BAG if url in available]
    if not START_VIDEO_BAG:
        START_VIDEO_BAG = available[:]
        random.shuffle(START_VIDEO_BAG)
    return START_VIDEO_BAG.pop() if START_VIDEO_BAG else None


async def run_start_animation(chat_id):
    header = "╭━━━『 ZYRA ENGINE 』━━━╮"
    footer = "╰━━━━━━━━━━━━━━━━━━━━╯"
    base = (
        f"{header}\n\n"
        "  Initializing ZYRA Core...\n"
        "  Connecting to Main Server...\n"
        "  Loading Userbot Modules...\n"
        "  Encrypting Session...\n"
        "  Checking System Status..."
    )
    frames = [
        f"{header}\n\n  Initializing ZYRA Core...\n{footer}",
        f"{header}\n\n  Initializing ZYRA Core...\n  Connecting to Main Server...\n{footer}",
        f"{header}\n\n  Initializing ZYRA Core...\n  Connecting to Main Server...\n  Loading Userbot Modules...\n{footer}",
        f"{header}\n\n  Initializing ZYRA Core...\n  Connecting to Main Server...\n  Loading Userbot Modules...\n  Encrypting Session...\n{footer}",
        f"{base}\n{footer}",
        f"{base}\n\n  [████░░░░░░░░░░░░] 25%\n{footer}",
        f"{base}\n\n  [████████░░░░░░░░] 50%\n{footer}",
        f"{base}\n\n  [████████████░░░░] 75%\n{footer}",
        f"{base}\n\n  [████████████████] 100%\n\n  ✓ ENGINE INITIALIZED\n{footer}",
        f"{base}\n\n  [████████████████] 100%\n\n  ✓ ENGINE INITIALIZED\n  ✓ ALL SYSTEMS ONLINE\n\n{footer}",
    ]

    status = await bot.send_message(chat_id, frames[0], parse_mode=None, link_preview=False)
    for frame in frames[1:]:
        await asyncio.sleep(0.9)
        try:
            await status.edit(frame, parse_mode=None, link_preview=False)
        except Exception as ex:
            log.warning("Start animation edit failed: %s", ex)
            break

    await asyncio.sleep(1.1)
    try:
        await status.delete()
    except Exception as ex:
        log.warning("Could not delete completed start animation: %s", ex)
    return status


async def send_start_menu(chat_id, reply_to=None, user_name=None):
    if not user_name:
        try:
            user = await bot.get_entity(chat_id)
            user_name = getattr(user, "first_name", None) or getattr(user, "title", None) or "there"
        except Exception:
            user_name = "there"
    welcome_text = build_welcome_text(user_name)

    if START_ANIMATION_ENABLED:
        await run_start_animation(chat_id)

    try:
        if START_STICKER_MESSAGE is not None:
            await bot.send_file(chat_id, START_STICKER_MESSAGE, reply_to=reply_to)
        elif START_STICKER_ID:
            await bot.send_file(chat_id, START_STICKER_ID, reply_to=reply_to)
    except Exception as ex:
        log.warning("Start sticker could not be sent: %s", ex)

    video_url = pick_welcome_video()
    if video_url:
        try:
            await bot.send_file(
                chat_id, video_url, caption=welcome_text,
                buttons=start_buttons(), parse_mode="html", reply_to=reply_to,
                supports_streaming=True,
            )
            return
        except Exception as ex:
            log.warning("Remote welcome video send failed; using fallback media: %s", ex)

    media_path = WELCOME_ANIMATION if WELCOME_ANIMATION and os.path.isfile(WELCOME_ANIMATION) else WELCOME_IMAGE
    try:
        await bot.send_file(chat_id, media_path, caption=welcome_text, buttons=start_buttons(),
                            parse_mode="html", reply_to=reply_to)
    except Exception as ex:
        log.warning("Welcome media could not be sent; using text fallback: %s", ex)
        await bot.send_message(chat_id, welcome_text, buttons=start_buttons(), parse_mode="html", reply_to=reply_to)


@bot.on(events.NewMessage(pattern=r"^/start(?:@\w+)?(?:\s+.*)?$"))
async def cmd_start(e):
    log.info("/start received user_id=%s", e.sender_id)

    try:
        await bot(functions.messages.SendReactionRequest(
            peer=e.peer_id,
            msg_id=e.id,
            reaction=[types.ReactionEmoji(emoticon="🦄")],
        ))
    except Exception as ex:
        log.warning("Unicorn start reaction failed; continuing: %s", ex)

    sender = e.sender
    first_name = (getattr(sender, "first_name", None) or "there").strip()
    asyncio.create_task(record_start_user(e.sender_id, first_name, getattr(sender, "username", None)))
    await send_start_menu(e.chat_id, user_name=first_name)


async def record_start_user(user_id, first_name, username):
    try:
        start_record = await bot_start_users.find_one({"_id": int(user_id)})
        if start_record:
            return
        await bot_start_users.update_one(
            {"_id": int(user_id)},
            {"$set": {"name": first_name, "username": username}},
            upsert=True,
        )
        username_line = f"\n♧ Username: @{html.escape(username)}" if username else "\n♧ Username: <i>not set</i>"
        total_started = await bot_start_users.count_documents({})
        await send_logger_log(
            "🪄 <b>NEW BOT USER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👤 Name: <b>{html.escape(first_name)}</b>\n"
            f"🆔 ID: <code>{user_id}</code>"
            f"{username_line}\n"
            f"📊 First-time users: <b>{total_started}</b>\n"
            "✨ <i>Zyra just got a new visitor!</i>"
        )
    except Exception as ex:
        log.warning("Could not record /start event: %s", ex)


def is_welcome_media_message(event):
    return bool(
        OWNER_ID
        and event.is_private
        and event.sender_id == OWNER_ID
        and event.media
        and not getattr(event, "via_bot_id", None)
    )


@bot.on(events.NewMessage(func=is_welcome_media_message))
async def sticker_id_helper(e):
    global START_STICKER_MESSAGE
    if not await require_panel_access(e):
        return
    try:
        START_STICKER_MESSAGE = e
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


@bot.on(events.NewMessage(pattern=r
