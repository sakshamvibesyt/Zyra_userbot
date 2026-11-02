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

## Free web service chahiye to

render.yaml me `type: worker` -> `type: web`, `plan: starter` -> `plan: free`, aur
`healthCheckPath: /health` add karo. Phir cron-job.org se `https://<app>.onrender.com/health`
har 5 min ping karwao. Free pe 12 se zyada users mat lo (512MB RAM).

## Plugins

`plugins/` me file daalo, `setup(client)` function rakho, pattern ke liye
`client.prefix` use karo. `/plugins` se on/off.
