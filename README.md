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
- `.afk [message]`, `.unafk` — custom AFK message; state survives worker restarts
- `.afkmsg <message>` — save any plain-text/emoji/multiline default AFK reply; `.afkmsg` displays it
- AFK clears automatically when you send a normal outgoing message (commands do not clear it)
- `.note <name> | <content>`, `.getnote <name>`, `.delnote <name>`, `.notes`
- `.autoreply <trigger> | <response>`, `.delreply <trigger>`, `.replies`
- `.filter <trigger> | <response>`, `.stop <trigger>`, `.filters`
- Admin tools: `.adminhelp`, `.ban`, `.unban`, `.mute`, `.unmute`, `.kick`, `.purge 20`, `.pin`, `.unpin`, `.del`, `.admins`, `.id`

Notes, auto-replies and filters are stored in MongoDB. Keep `MONGO_URL` private. Only use moderation commands in chats where you have permission; avoid unsolicited automated messages.


## Zyra welcome menu

`/start` now attempts a 👋 reaction, optionally sends `START_STICKER_ID`, then displays the bundled `assets/zyra_welcome.png` banner with **Add Account**, **Help**, and **Owner** buttons. The reaction is best-effort because Telegram may restrict reactions in some bot/chat configurations.

- `OWNER_URL` changes the Owner button destination.
- `START_STICKER_ID` is optional; set it to a sticker `file_id` to enable the sticker step. Leave it blank to skip the sticker.
- The welcome banner is `assets/zyra_welcome.png`; replace it with your own banner using the same filename if desired.

The Add Account button opens the existing login flow. Never share OTPs or 2-step verification passwords with anyone; only connect an account you own.
\n\n## Add Account callback fix\n\nThe Add Account inline button now initializes the phone login state and replies with the expected instructions. `/cancel` clears an in-progress login. This still requires deployment and a Telegram test.\n

## Full interface update

- `/help` and the Start menu Help button open an inline help center.
- Help sections cover account/settings, utilities, social tools, admin tools, and AI/plugins.
- The userbot `.help` output is formatted as a categorized command reference.
- Add Account sends its phone-number prompt directly to the private chat.

Please deploy and test all Telegram callbacks on your own bot; platform permissions and configured environment variables can affect behavior.


## Profile template commands

- Reply to a user message with `.clone`, or use `.clone @username`, to copy the name, bio and up to five available profile photos.
- `.reclone` or `.revert` restores the original profile snapshot saved before the first clone.
- Use profile copying only with the person’s permission; do not impersonate or mislead others.
- MongoDB is used to store the original profile snapshot; keep `MONGO_URL` private.


## Custom AFK behavior

- `.afkmsg I'm away right now ✨` saves a default message. Newlines, emoji, symbols, and long plain-text messages are supported up to 3500 characters.
- `.afk optional one-time message` activates AFK with that message instead of the saved default.
- `.afk` activates the saved default; `.unafk` disables it.
- AFK state and the saved message are stored in MongoDB, so they survive a worker restart. AFK replies are sent in private chats or when someone mentions the account in a group.
- Telegram does not provide a dependable event telling a userbot that the owner merely closed their separate Telegram app or became “offline”. This implementation therefore clears AFK on the next normal outgoing message rather than claiming to detect app presence.


## Trusted panel admins

Set `OWNER_ID` in Render to your own numeric Telegram user ID. Only this ID can add/remove panel admins.

- `/addadmin 123456789` — owner-only, add a trusted admin by numeric Telegram user ID.
- `/removeadmin 123456789` — owner-only, remove an admin.
- `/admins` — list trusted admins.

Admin IDs are stored in MongoDB. Admins can use the control-panel commands for their own Telegram account and the userbot tools on their own connected account. This does not hand an admin your personal Telegram session. Keep `OWNER_ID` private and do not share OTPs, 2FA passwords, or session strings.

## AFK and profile template

- `.afk your custom message` — activate AFK with arbitrary text, emoji, symbols, or multiple lines.
- `.afkmsg your default message` — save a default message; `.afkmsg` shows it.
- `.unafk` — clear AFK.
- `.clone` works by replying to a user message; `.clone @username` works by username. `.reclone` and `.revert` restore the saved original profile. Use only with permission.

Telegram does not provide a reliable signal that your separate Telegram app was closed, so AFK cannot safely auto-enable solely when you close the app. It clears when you send a normal outgoing message.

## Feature scope

Zyra includes modular plugins, AI (when configured), notes, AFK, auto-replies, profile template backup/restore, and permission-based group moderation. It intentionally does not implement raid/spam automation, mass-add/promote automation, or hidden engagement/view manipulation.
