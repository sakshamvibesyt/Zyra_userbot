# Userbot Host

Multi-user Telegram userbot. Har user apna account add karke apne plugins chala sakta hai.

## Env vars

| Key | Kahan se |
|---|---|
| API_ID / API_HASH | https://my.telegram.org/apps |
| BOT_TOKEN | @BotFather (master bot) |
| MONGO_URL | MongoDB Atlas M0 (free) |
| SESSION_KEY | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
| VENICE_API_KEY | https://venice.ai (AI plugin ke liye) |

## Deploy

1. Repo private rakho.
2. Render pe Blueprint deploy karo (render.yaml use karega) — Background Worker, plan starter.
3. Env vars bharo.
4. Bot ko /start -> Login -> phone -> OTP -> 2FA.
5. User `.ping` chala kar test kare.

## Render Free Web Service note

Free Web Services can sleep after 15 minutes without inbound HTTP requests. The `/health`
endpoint is useful for checking status, but periodic pings are not a reliable or guaranteed
way to keep a Free service awake. This project now checks connected user clients every 30
seconds and attempts to reconnect after transient Telegram/network disconnects; it cannot
override Render's sleep policy. For reliable always-on operation, use a paid Background Worker
(or a paid Web Service if inbound HTTP is required). The included `render.yaml` is configured
as a paid Background Worker (`plan: starter`), so review the plan before deploying it.

## Plugins

`plugins/` me file daalo, `setup(client)` function rakho, pattern ke liye
`client.prefix` use karo. `/plugins` se on/off.


## Extra commands (added)

The `extras` plugin adds these commands to each connected user account (default prefix `.`):

- `.help` — show userbot commands
- `.alive` — check userbot status
- `.echo <text>`, `.type <text>`, `.calc <expression>`
- `.reverse <text>`, `.clap <text>`, `.emojify <text>`, `.spoiler <text>`
- `.afk [reason]`, `.unafk` — temporary AFK status (resets after worker restart)
- `.note <name> | <content>`, `.getnote <name>`, `.delnote <name>`, `.notes`
- `.autoreply <trigger> | <response>`, `.delreply <trigger>`, `.replies`
- `.filter <trigger> | <response>`, `.stop <trigger>`, `.filters`
- Admin tools: `.adminhelp`, `.ban`, `.unban`, `.mute`, `.unmute`, `.kick`, `.purge 20`, `.pin`, `.unpin`, `.del`, `.admins`, `.id`

Notes, auto-replies and filters are stored in MongoDB. Keep `MONGO_URL` private. Only use moderation commands in chats where you have permission; avoid unsolicited automated messages.
