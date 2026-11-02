import os
import aiohttp
from telethon import events

KEY = os.environ.get("VENICE_API_KEY", "")
MODEL = os.environ.get("AI_MODEL", "venice-uncensored")
BASE = os.environ.get("AI_BASE_URL", "https://api.venice.ai/api/v1")
SYSTEM = os.environ.get("AI_SYSTEM", "Short, casual, Hinglish replies.")


async def ask(prompt):
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
    return d["choices"][0]["message"]["content"].strip()


def setup(client):
    if not KEY:
        return
    p = client.prefix

    @client.on(events.NewMessage(pattern=r"^" + p + r"ai (.+)", outgoing=True))
    async def cmd(e):
        m = await e.reply("...")
        try:
            await m.edit(await ask(e.pattern_match.group(1)))
        except Exception as ex:
            await m.edit("<code>%s</code>" % ex)
