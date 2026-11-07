"""Premium text dashboard for a connected Telegram user account.

Telegram inline keyboards are bot-only; the userbot dashboard therefore uses
clear command navigation instead of non-working callback buttons.
"""
import html
import re
import os
from telethon import events
import db as database


def setup(client):
    uid = int(client.uid)
    promo = database.db.zyra_promo_config
    dmtrap = database.db.zyra_dmtrap_config
    groups = database.db.zyra_promo_groups
    subscribers = database.db.zyra_promo_subscribers
    ai_settings = database.db.zyra_ai_settings

    async def render_page(page="home"):
        p = html.escape(client.prefix)
        pcfg = await promo.find_one({"uid": uid}) or {}
        dcfg = await dmtrap.find_one({"uid": uid}) or {}
        promo_on = pcfg.get("enabled", os.environ.get("AUTO_PROMO", "false").lower() == "true")
        dm_on = dcfg.get("enabled", True)
        group_count = await groups.count_documents({"uid": uid, "enabled": True})
        dm_count = await subscribers.count_documents({"uid": uid, "enabled": True})
        if page == "tags":
            return ("<b>🏷 SMART TAG CENTER</b>\n\n"
                    f"<code>{p}tagrefresh</code> — scan visible group members\n"
                    f"<code>{p}tagall message</code> — admin-only group mentions\n"
                    f"<code>{p}taglist</code> — saved/opt-out count\n"
                    f"<code>{p}tagstop</code> — stop current run\n"
                    f"<code>{p}tagjoin</code> / <code>{p}tagleave</code> — opt in/out\n"
                    f"<code>{p}tagclear</code> — clear current group index\n\n"
                    "Telegram may limit participant discovery. Respect group rules and opt-outs.")
        if page == "promo":
            return ("<b>📢 AUTO PROMO</b>\n\n"
                    f"Status: <b>{'ON ✅' if promo_on else 'OFF 🛑'}</b>\n"
                    f"Groups enrolled: <b>{group_count}</b> · Opt-in DMs: <b>{dm_count}</b>\n\n"
                    f"<code>{p}promo on/off</code>\n<code>{p}promo set Your message</code>\n"
                    f"<code>{p}promo add JOIN | https://t.me/group</code>\n<code>{p}promo time 12h</code>\n"
                    f"<code>{p}promo status</code> · <code>{p}promo test</code>")
        if page == "dm":
            return ("<b>💌 DM TRAP</b>\n\n"
                    f"Status: <b>{'ON ✅' if dm_on else 'OFF 🛑'}</b>\n"
                    f"<code>{p}dmtrap on/off/status</code>\n"
                    f"<code>{p}dmtrap set Your reply {{first_name}}</code>\n"
                    f"<code>{p}dmtrap cooldown 3600</code>\n<code>{p}dmtrap reset</code>")
        if page == "ai":
            acfg = await ai_settings.find_one({"uid": uid}) or {}
            return ("<b>🧠 AI BRAIN</b>\n\n"
                    f"Chat replies: <b>{'ON' if acfg.get('auto_enabled') else 'OFF'}</b>\n"
                    f"Sticker reactions: <b>{'ON' if acfg.get('sticker_enabled') else 'OFF'}</b>\n\n"
                    f"<code>{p}ai your question</code> — ask AI\n"
                    f"<code>{p}ai auto on/off</code> — reply when mentioned/replied to\n"
                    f"<code>{p}ai sticker on/off</code> — react to stickers replying to you\n"
                    f"<code>{p}ai status</code> — view AI status\n\n"
                    "AI requires VENICE_API_KEY and AI_MODEL in Render environment variables.")
        return ("<b>✦ 𝐙𝐘𝐑𝐀 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃 ✦</b>\n"
                "<i>Dark control center · Account workspace</i>\n\n"
                f"📢 Auto Promo: <b>{'ON' if promo_on else 'OFF'}</b>\n"
                f"💌 DM Trap: <b>{'ON' if dm_on else 'OFF'}</b>\n"
                f"👥 Promo groups: <b>{group_count}</b> · DM subscribers: <b>{dm_count}</b>\n\n"
                "<b>MODULES</b>\n"
                f"<code>{p}dashboard promo</code> · Auto Promo\n"
                f"<code>{p}dashboard dm</code> · DM Trap\n"
                f"<code>{p}dashboard tags</code> · Smart Tags\n"
                f"<code>{p}dashboard ai</code> · AI Brain\n"
                f"<code>{p}promo trigger on/off</code> · Promo when mentioned/replied to\n\n"
                "<i>Use the commands shown in each module to control settings.</i>")

    @client.on(events.NewMessage(pattern=r"^" + re.escape(client.prefix) + r"dashboard(?:\s+(home|promo|dm|tags|ai))?$", outgoing=True))
    async def dashboard_command(e):
        page = (e.pattern_match.group(1) or "home").lower()
        body = await render_page(page)
        await e.edit(body, parse_mode="html")
