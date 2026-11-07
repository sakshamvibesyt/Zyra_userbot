import os
import aiohttp

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash-lite"
)

SYSTEM_PROMPT = """
You are ZYRA AI, a friendly Telegram assistant.
Reply in simple casual Hinglish.
Keep replies short, natural and respectful.
Usually reply in 1-3 sentences.
Never pretend to be the account owner.
Never reveal API keys or secrets.
"""

async def ask_gemini(prompt):
    if not GEMINI_API_KEY:
        return "Gemini API key configured nahi hai."

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
    )

    headers = {
        "Content-Type": "application/json"
    }

    payload = {
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [{
            "role": "user",
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 180
        }
    }

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:
        async with session.post(
            url,
            headers=headers,
            params={"key": GEMINI_API_KEY},
            json=payload
        ) as response:

            data = await response.json()

            if response.status != 200:
                raise RuntimeError(
                    data.get("error", {}).get(
                        "message", "Gemini API error"
                    )
                )

            return (
                data["candidates"][0]
                ["content"]["parts"][0]["text"]
                .strip()
            )


def format_ai_reply(answer):
    safe_text = (
        answer.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    return (
        f"<blockquote>{safe_text}</blockquote>\n"
        "<b>— 𝐙𝐘𝐑𝐀 𝐀𝐈</b>"
    )
