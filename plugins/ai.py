import os
import re
import aiohttp
from telethon import events

KEY = os.environ.get("VENICE_API_KEY", "")
MODEL = os.environ.get("AI_MODEL", "venice-uncensored")
BASE = os.environ.get("AI_BASE_URL") or os.environ.get("VENICE_BASE_URL", "https://api.venice.ai/api/v1")
SYSTEM = os.environ.get("AI_SYSTEM", "Short, casual, Hinglish replies.")


async def ask(prompt):
    if not KEY:
        raise RuntimeError("VENICE_API_KEY is missing in Render environment variables")
    payload = {
        "model": MODEL,
        "temperature": 0.8,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.post(BASE + "/chat/completions", json=payload, headers=h, timeout=60) as r:
            d = await r.json()
            if r.status >= 400:
                raise RuntimeError(d.get("error", {}).get("message", f"AI provider returned HTTP {r.status}"))
    try:
        return d["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("AI provider returned an unexpected response")


def setup(client):
    p = re.escape(client.prefix)

    @client.on(events.NewMessage(pattern=r"^" + p + r"ai\s+(.+)$", outgoing=True))
    async def cmd(e):
        m = await e.reply("...")
        try:
            await m.edit(await ask(e.pattern_match.group(1)))
        except Exception as ex:
            import html
            await m.edit("⚠️ <b>AI request failed</b>\n<code>%s</code>" % html.escape(str(ex)[:250]), parse_mode="html")
