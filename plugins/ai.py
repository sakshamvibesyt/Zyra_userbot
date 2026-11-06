import re
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
    timeout = aiohttp.ClientTimeout(total=35, connect=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(BASE.rstrip("/") + "/chat/completions", json=payload, headers=h) as r:
            if r.status >= 400:
                detail = (await r.text())[:300]
                raise RuntimeError(f"AI service returned HTTP {r.status}: {detail}")
            d = await r.json(content_type=None)
    choices = d.get("choices") or []
    if not choices:
        raise RuntimeError("AI service returned an empty response.")
    return (choices[0].get("message", {}).get("content") or "").strip() or "AI ne empty reply diya."


def setup(client):
    if not KEY:
        return
    p = client.prefix

    @client.on(events.NewMessage(pattern=r"^" + re.escape(p) + r"ai\s+([\s\S]+)$", outgoing=True))
    async def cmd(e):
        prompt = e.pattern_match.group(1).strip()
        if len(prompt) > 3000:
            return await e.edit("Prompt 3000 characters se chhota rakho.")
        m = await e.reply("🖤 <b>ZYRA AI is thinking…</b>", parse_mode="html")
        try:
            answer = await ask(prompt)
            await m.edit(answer[:3900])
        except Exception as ex:
            await m.edit("⚠️ <b>AI request failed.</b>\\n<code>%s</code>" % __import__("html").escape(str(ex)[:250]), parse_mode="html")
