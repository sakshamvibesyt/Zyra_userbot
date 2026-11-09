"""Advanced text dashboard with account, group, AI and activity summaries."""
import html
import re
import os
import time
from telethon import events
import db as database


def setup(client):
    uid = int(client.uid)
    promo = database.db.zyra_promo_config
    dmtrap = database.db.zyra_dmtrap_config
    promo_groups = database.db.zyra_promo_groups
    subscribers = database.db.zyra_promo_subscribers
    ai_settings = database.db.zyra_ai_settings
    seen_groups = database.db.zyra_seen_groups
    logs = database.db.zyra_activity_logs
    ignored_users = database.db.zyra_ignored_users
    ignored_chats = database.db.zyra_ignored_chats
    afk_states = database.db.zyra_afk_states
    sticker_replies = database.db.zyra_sticker_replies

    async def render(page="home"):
        p = html.escape(client.prefix)
        pcfg = await promo.find_one({"uid": uid}) or {}
        dcfg = await dmtrap.find_one({"uid": uid}) or {}
        acfg = await ai_settings.find_one({"uid": uid}) or {}
        promo_on = pcfg.get("enabled", os.environ.get("AUTO_PROMO", "false").lower() == "true")
        group_count = await seen_groups.count_documents({"uid": uid})
        group_messages = 0
        async for g in seen_groups.find({"uid": uid}):
            group_messages += int(g.get("message_count", 0))
        log_count = await logs.count_documents({"uid": uid})
        ai_requests = await logs.count_documents({"uid": uid, "kind": {"$in": ["ai_request", "ai_auto"]}})
        error_count = await logs.count_documents({"uid": uid, "kind": "error"})
        ignored_u = await ignored_users.count_documents({"uid": uid})
        ignored_c = await ignored_chats.count_documents({"uid": uid})
        sticker_count = await sticker_replies.count_documents({"uid": uid})
        afk = await afk_states.find_one({"uid": uid}) or {}
        if page == "groups":
            items = await seen_groups.find({"uid": uid}).sort("last_seen", -1).to_list(length=30)
            lines = ["• <b>%s</b> — %s msgs · %s" % (html.escape(x.get("title", "Group")), int(x.get("message_count", 0)), time.strftime("%d %b %H:%M", time.localtime(x.get("last_seen", 0)))) for x in items]
            return "<b>👥 GROUP ACTIVITY</b>\n\n" + ("\n".join(lines) or "No group activity logged yet.") + f"\n\nGroups tracked: <b>{group_count}</b> · Total activity: <b>{group_messages}</b>"
        if page == "logs":
            items = await logs.find({"uid": uid}).sort("at", -1).to_list(length=15)
            lines = []
            for x in items:
                stamp = time.strftime("%d %b %H:%M", time.localtime(x.get("at", 0)))
                actor = html.escape(x.get("sender_name", "")[:35])
                detail = html.escape(x.get("detail", "")[:70])
                lines.append("• <code>%s</code> · <b>%s</b> · %s · %s\n  <i>%s</i>" % (stamp, html.escape(x.get("kind", "event")), html.escape(x.get("title", "")), actor, detail))
            return "<b>🧾 RECENT LOGS</b>\n\n" + ("\n".join(lines) or "No logs yet.") + "\n\n<i>Message content is not stored.</i>"
        if page == "ignore":
            return ("<b>🚫 IGNORE CENTER</b>\n\n" + f"Ignored users: <b>{ignored_u}</b>\nIgnored chats: <b>{ignored_c}</b>\n\n"
                f"<code>{p}ignore @username</code> or reply + <code>{p}ignore</code>\n"
                f"<code>{p}unignore @username</code>\n<code>{p}ignorechat</code> / <code>{p}unignorechat</code>\n<code>{p}ignored</code>")
        if page == "afk":
            return ("<b>🌙 ADVANCED AFK</b>\n\n" + f"Status: <b>{'ON' if afk.get('active') else 'OFF'}</b>\n"
                f"Mentions/replies counted: <b>{int(afk.get('mention_count', 0))}</b>\n\n"
                f"<code>{p}afk busy | 2h</code> — reason + optional duration\n<code>{p}afkmsg text</code> — default message\n"
                f"<code>{p}afkstats</code> — stats · <code>{p}unafk</code> — return")
        if page == "ai":
            return ("<b>🧠 ZYRA AI</b>\n\n" + f"Auto replies: <b>{'ON' if acfg.get('auto_enabled') else 'OFF'}</b>\n"
                f"Sticker reactions: <b>{'ON' if acfg.get('sticker_enabled') else 'OFF'}</b>\n"
                f"Conversation memory: <b>{'ON' if acfg.get('memory_enabled', True) else 'OFF'}</b>\n\n"
                f"<code>{p}ai question</code> · <code>{p}ai auto on/off</code>\n<code>{p}ai memory on/off</code> · <code>{p}ai clear</code>\n"
                "Provider: Gemini · Requires GEMINI_API_KEY")
        if page == "promo":
            enrolled = await promo_groups.count_documents({"uid": uid, "enabled": True})
            return f"<b>📢 AUTO PROMO</b>\nStatus: <b>{'ON' if promo_on else 'OFF'}</b>\nGroups enrolled: <b>{enrolled}</b>\n<code>{p}promo on/off</code> · <code>{p}promo status</code>"
        if page == "dm":
            return f"<b>💌 DM AUTO REPLY</b>\nStatus: <b>{'ON' if dcfg.get('enabled', True) else 'OFF'}</b>\n<code>{p}dmtrap on/off/status</code> · <code>{p}dmtrap cooldown 3600</code>"
        me = await client.get_me()
        started = float(getattr(client, "zyra_started_at", time.time()))
        uptime = max(0, int(time.time() - started))
        uptime_text = "%dd %dh %dm" % (uptime // 86400, (uptime % 86400) // 3600, (uptime % 3600) // 60)
        return ("<b>✦ 𝐙𝐘𝐑𝐀 𝐀𝐃𝐕𝐀𝐍𝐂𝐄𝐃 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃 ✦</b>\n<i>Account command center · Live MongoDB stats</i>\n\n"
            f"👤 Account: <b>{html.escape(me.first_name or 'Telegram user')}</b> · <code>{me.id}</code>\n⏱ Uptime: <b>{uptime_text}</b>\n"
            f"👥 Groups tracked: <b>{group_count}</b>\n💬 Group activity count: <b>{group_messages}</b>\n🧠 AI requests: <b>{ai_requests}</b>\n"
            f"🧾 Recent log records: <b>{log_count}</b> · ⚠️ Errors: <b>{error_count}</b>\n"
            f"🚫 Ignored users/chats: <b>{ignored_u}/{ignored_c}</b>\n🎭 Sticker rules: <b>{sticker_count}</b>\n"
            f"🧠 AI: <b>{'ON' if acfg.get('auto_enabled') else 'OFF'}</b> · 🌙 AFK: <b>{'ON' if afk.get('active') else 'OFF'}</b>\n\n"
            "<b>SECTIONS</b>\n" + "\n".join(f"<code>{p}dashboard {x}</code>" for x in ("groups", "logs", "ignore", "afk", "ai", "promo", "dm")) +
            "\n\n<i>Logs record activity metadata only; message text is not saved.</i>")

    @client.on(events.NewMessage(pattern=r"^" + re.escape(client.prefix) + r"dashboard(?:\s+(home|groups|logs|ignore|afk|ai|promo|dm))?$", outgoing=True))
    async def dashboard_command(e):
        await e.edit(await render((e.pattern_match.group(1) or "home").lower()), parse_mode="html")
