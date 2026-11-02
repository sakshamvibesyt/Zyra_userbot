import asyncio, logging, os, time

from aiohttp import web
from telethon import TelegramClient, events, Button
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


HELP = """<b>Commands</b>
/login — apna account add karo
/logout — account hatao
/status — apna status
/prefix . — command prefix badlo
/plugins — plugin on/off
/help — ye list"""


@bot.on(events.NewMessage(pattern=r"^/start$"))
async def cmd_start(e):
    await e.reply(
        "<b>Userbot Host</b>\n\nApna account add karo, plugins chalao.\n"
        "Session encrypted store hoti hai, 2FA kabhi save nahi hota.",
        buttons=[[Button.inline("Login", b"login")]],
    )


@bot.on(events.CallbackQuery(data=b"login"))
async def cb_login(e):
    await e.answer()
    await start_login(e.sender_id, e)


async def start_login(uid, e):
    doc = await db.users.find_one({"_id": uid})
    if doc and not doc.get("dead"):
        return await e.reply("Already logged in. Pehle /logout karo.")
    if await db.users.count_documents({}) >= MAX_USERS:
        return await e.reply("Server full (%s). Baad me try karo." % MAX_USERS)
    states[uid] = {"step": "phone"}
    await e.reply("Phone number bhejo country code ke saath, jaise +919876543210")


@bot.on(events.NewMessage(pattern=r"^/login$"))
async def cmd_login(e):
    await start_login(e.sender_id, e)


@bot.on(events.NewMessage(pattern=r"^/help$"))
async def cmd_help(e):
    await e.reply(HELP)


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
