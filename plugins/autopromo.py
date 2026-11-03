"""Configurable, rate-limited channel promo plugin for Zyra."""
import os, random, asyncio, html
from telethon import events
import db as database

DEFAULT_ON = os.environ.get("AUTO_PROMO", "false").lower() == "true"
TEXT = os.environ.get("PROMO_TEXT", "🔗 {channel}")
CHANNEL = os.environ.get("PROMO_CHANNEL", "")
CHANCE = float(os.environ.get("PROMO_CHANCE", "0.05"))
COOL = int(os.environ.get("PROMO_COOLDOWN", "300"))


def setup(client):
    p = __import__("re").escape(client.prefix)
    uid = client.uid
    states = database.db.zyra_promo_states
    last = {}

    async def enabled():
        doc = await states.find_one({"uid": uid})
        return bool(doc.get("enabled")) if doc else DEFAULT_ON

    async def stylish_reply(e, title, body, footer="✦ ᴢʏʀᴀ ᴀᴜᴛᴏ-ᴅʀᴏᴘ ✦"):
        # Send a separate, styled reply, then remove the command message.
        message = (
            "<blockquote>🎀 <b>" + title + "</b> ✨💜\n"
            "━━━━━━━━━━━━━━━━━━\n"
            + body + "\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "<i>" + footer + "</i></blockquote>"
        )
        await e.reply(message, parse_mode="html")
        try:
            await e.delete()
        except Exception:
            pass

    @client.on(events.NewMessage(pattern=r"^" + p + r"promo(?:\s+(on|off|status))?$", outgoing=True))
    async def promo_control(e):
        action = (e.pattern_match.group(1) or "status").lower()
        if action == "on":
            if not CHANNEL:
                return await stylish_reply(
                    e, "SETUP REQUIRED",
                    "⚠️ <b>PROMO_CHANNEL</b> environment variable set karo, phir <code>%spromo on</code> chalao." % html.escape(client.prefix),
                    "✦ ᴢʏʀᴀ ᴄᴏɴꜰɪɢ ✦",
                )
            await states.update_one({"uid": uid}, {"$set": {"enabled": True}}, upsert=True)
            return await stylish_reply(
                e, "AUTO-DROP ON HO GAYA! 💅",
                "👑 <b>Zyra Auto-Drop</b> is now <b>ON</b> ✅\nAb configured channel promo enabled hai! 🚀",
                "✦ ᴅʀᴀᴍᴀ ꜱʜᴜʀᴜ ✦",
            )
        if action == "off":
            await states.update_one({"uid": uid}, {"$set": {"enabled": False}}, upsert=True)
            return await stylish_reply(
                e, "AUTO-DROP BAND KAR DIYA CUTIE 🛑",
                "🌙 <b>Zyra Auto-Drop</b> is now <b>OFF</b> ❌\nAuto-promo pause kar diya gaya hai.",
                "✦ ᴅʀᴏᴘ ᴘᴀᴜꜱᴇᴅ ✦",
            )
        state = "ON ✅" if await enabled() else "OFF 🛑"
        await stylish_reply(
            e, "AUTO-DROP STATUS",
            "👑 <b>Status:</b> " + state + "\n🔗 <b>Channel:</b> <code>" + html.escape(CHANNEL or "not configured") + "</code>",
            "✦ ᴢʏʀᴀ ꜱᴛᴀᴛᴜꜱ ✦",
        )

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group))
    async def promo(e):
        if not CHANNEL or not await enabled():
            return
        now = asyncio.get_event_loop().time()
        if now - last.get(e.chat_id, 0) < COOL:
            return
        if random.random() > CHANCE:
            return
        last[e.chat_id] = now
        try:
            await e.reply(TEXT.format(channel=CHANNEL))
        except Exception:
            pass
