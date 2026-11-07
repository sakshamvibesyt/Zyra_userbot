# Userbot Host

Multi-user Telegram userbot. Har user apna account add karke apne plugins chala sakta hai.

## Env vars

| Key | Kahan se |
|---|---|
| API_ID / API_HASH | https://my.telegram.org/apps |
| BOT_TOKEN | @BotFather (master bot) |
| MONGO_URL | MongoDB Atlas M0 (free) |
| SESSION_KEY | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
| GEMINI_API_KEY | Google AI Studio API key (keep private in Render) |
| GEMINI_MODEL | `gemini-2.5-flash-lite` |

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

## ZYRA AI (Gemini)

Set `GEMINI_API_KEY` and `GEMINI_MODEL=gemini-2.5-flash-lite` in Render. Commands on each connected account (default prefix `.`):

- `.ai status` — show key/model and feature status
- `.ai auto on/off` — enable/disable opt-in private replies and group mention/reply responses
- `.ai sticker on/off` — enable/disable short sticker reactions (sticker image itself is not analyzed)
- `.ai <question>` — ask Gemini directly

AI replies use a Telegram quote block with the `— 𝐙𝐘𝐑𝐀 𝐀𝐈` signature. Free-tier rate limits may apply.

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

`/start` attempts a 👋 reaction, runs a short three-frame ZYRA loading animation, optionally sends `START_STICKER_ID`, then sends a remote MP4 from the preserved `START_VIDEO_URLS` rotation with **Add Account**, **Help**, Support and Owner buttons. The reaction is best-effort because Telegram may restrict reactions in some bot/chat configurations.

- `OWNER_URL` changes the Owner button destination.
- `START_STICKER_ID` is optional; set it to a sticker `file_id` to enable the sticker step. Leave it blank to skip the sticker.
- If Telegram cannot fetch a remote video URL, the static `assets/zyra_welcome.png` banner is used as fallback. The welcome video itself is never replaced with a bundled local MP4.

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

Zyra includes modular plugins, AI (when configured), notes, AFK, auto-replies, profile template backup/restore, permission-based group moderation, and an admin-triggered paced TagAll. It does not implement mass-add/promote automation or hidden engagement/view manipulation.


## Opt-in broadcast

The `plugins/broadcast.py` plugin sends a replied-to text/photo/media only to destinations that explicitly opted in. It does not message every group or every DM automatically.

- In each group you want to include, send `.broadcast here` from the connected account. Use `.broadcast leave` there to remove it.
- A person can DM the connected account `.broadcast subscribe`; they can send `.broadcast unsubscribe` at any time.
- Promotion Studio can include clickable HTML URL links. In the wizard, add links as `Label | https://t.me/yourlink` and finish with `/done`.
- Publish with `.promotion publish`; cancel with `.promotion cancel`.
- Telethon inline keyboards are bot-only, so the user-account userbot sends clickable text links and uses commands for preview/publish controls.
- `.broadcast status` shows destination counts; `.broadcast stop` requests cancellation.

This feature only targets subscribed DMs and groups that were explicitly added. Test with one opted-in destination first.
- The sender waits between destinations and respects Telegram FloodWait responses. Delivery can still fail due to permissions, blocks, or Telegram limits.

Keep existing Render environment variables unchanged. The plugin uses the project's existing MongoDB connection.


## DM auto-reply placeholders

`DM_TEXT` supports these placeholders, which are replaced separately for each person who messages a connected account:

- `{first_name}` — their first name
- `{name}` — same as first name
- `{username}` — their `@username` (empty if not set)
- `{mention}` — clickable mention
- `{id}` — their Telegram numeric ID

Example: `𓆩♡𓆪 𝐇𝐞𝐲𝐲 {first_name} 🎀`

Optional DM clickable links use `PROMO_LINKS` in `Label|https://example.com` format, separated by commas.

## Promotion Studio

- `.promotion` — compose media, caption and clickable URL links
- During the wizard, use `/skip` to skip media/caption/links and `/done` to finish links
- `.promotion publish` — publish the latest ready draft
- `.promotion preview` — reopen preview; `.promotion status` — draft/send status; `.promotion cancel` — cancel the draft
- `.broadcast here` / `.broadcast leave` — opt the current group in/out
- `.broadcast status` — opted-in destination counts; `.broadcast stop` — stop an active send
- DM recipients must opt in with `.broadcast subscribe` and can stop with `.broadcast unsubscribe`

The welcome MP4 list is hard-coded in `START_VIDEO_URLS` in `main.py`. The bot sends those external URLs directly through Telethon, preserving the no-repeat rotation. If Telegram cannot fetch a URL, it falls back to the static welcome banner and then text.


## ZYRA premium dashboard, TagAll and automatic promo update

- `.dashboard` — open the dark ZYRA text control panel with Auto Promo, DM Trap, Smart Tags and AI command sections. User-account sessions use command navigation because Telegram inline keyboards are bot-only.
- `.tagrefresh` — scan Telegram-visible group participants and save their public profile IDs group-wise. Telegram privacy/API restrictions can prevent a complete member list.
- `.tagall [message]` — refresh the member index, then mention eligible indexed members in batches. The connected account must be a group admin. `.taglist` shows saved/opted-out counts; `.tagstop` or `.tagcancel` stops a run; `.tagjoin` / `.tagleave` opt a member in/out; `.tagclear` clears the current group's index. A one-hour default per-group cooldown, batching and FloodWait handling are enabled.
- `TAGALL_MAX_MEMBERS` defaults to 5000; `TAGALL_BATCH_SIZE` defaults to 8; `TAGALL_DELAY_SECONDS` defaults to 3; `TAGALL_COOLDOWN` defaults to 3600 seconds. Do not use TagAll to harass or repeatedly ping people; respect group rules and member opt-outs.
- `.promo on` enables promotion for existing groups the connected account belongs to; new active groups are automatically enrolled. Each group gets at most one promo per configured interval (default 24 hours). `.promo group off` excludes a group. Private DM promos remain opt-in with `.promo subscribe` and `.promo unsubscribe`.
- Promo controls: `.promo set TEXT`, `.promo link URL`, `.promo add LABEL | URL`, `.promo remove N`, `.promo list`, `.promo time 12h`, `.promo image` (reply to media), `.promo test`, `.promo status`, `.promo off`. `PROMO_INTERVAL_SECONDS` defaults to 86400 seconds.
- DM Trap controls: `.dmtrap on/off/status`, `.dmtrap set TEXT`, `.dmtrap cooldown 3600`, `.dmtrap reset`.
- `/start` keeps the existing remote `START_VIDEO_URLS` list and no-repeat rotation. The loading animation is reduced to three quick frames; if all remote video delivery fails, the static welcome banner/text is used instead of a local MP4.
- AI now uses Google Gemini through `GEMINI_API_KEY` and `GEMINI_MODEL`; voice/audio AI is not included in this build.

### Auto Sticker Replies

The connected user account can save a Telegram sticker as an exact text-trigger reply:

1. Send the sticker in any chat (Saved Messages is convenient).
2. Reply to that sticker with `.setsticker hi` (replace `hi` with the trigger).
3. When an incoming message exactly matches `hi` (case-insensitive), the userbot sends the saved sticker as a reply.
4. Manage rules with `.stickers`, `.delsticker hi`, and `.sticker on`, `.sticker off`, or `.sticker status`.

Sticker source messages must remain available in Telegram because the userbot retrieves the original sticker message when it sends the reply. Auto sticker replies are enabled by default and have a short per-chat/sender trigger cooldown.
