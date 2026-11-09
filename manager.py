import asyncio, importlib, logging, os, pkgutil, time

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

import db, crypto

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]

log = logging.getLogger("manager")


class Manager:
    def __init__(self):
        self.clients = {}

    def load_plugins(self, client, disabled):
        import plugins
        for m in pkgutil.iter_modules(plugins.__path__):
            if m.name in disabled:
                continue
            try:
                mod = importlib.import_module("plugins." + m.name)
                if hasattr(mod, "setup"):
                    mod.setup(client)
            except Exception:
                log.exception("plugin %s failed uid=%s", m.name, client.uid)

    async def spawn(self, doc, client=None):
        uid = doc["_id"]
        if uid in self.clients:
            return self.clients[uid]

        if client is None:
            client = TelegramClient(
                StringSession(crypto.dec(doc["session"])), API_ID, API_HASH
            )
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                await db.users.update_one({"_id": uid}, {"$set": {"dead": True}})
                return None

        client.parse_mode = "html"
        me = await client.get_me()
        client.me_id = me.id
        client.uid = uid
        client.prefix = doc.get("prefix", ".")
        client.zyra_started_at = time.time()

        self.load_plugins(client, set(doc.get("disabled", [])))
        self.clients[uid] = client
        log.info("spawned uid=%s as %s", uid, me.first_name)
        return client

    async def kill(self, uid):
        c = self.clients.pop(uid, None)
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass

    async def boot_all(self):
        n = 0
        async for doc in db.users.find({"enabled": True, "dead": {"$ne": True}}):
            try:
                if await self.spawn(doc):
                    n += 1
            except FloodWaitError as e:
                log.warning("floodwait %ss", e.seconds)
                await asyncio.sleep(e.seconds)
            except Exception:
                log.exception("boot failed uid=%s", doc["_id"])
            await asyncio.sleep(2.5)
        log.info("booted %s clients", n)

    async def monitor_connections(self):
        """Reconnect existing user clients when their Telegram connection drops.

        This repairs transient Telegram/network disconnects without periodically
        restarting the whole process. It cannot prevent Render Free from sleeping.
        """
        while True:
            for uid, client in list(self.clients.items()):
                try:
                    if client.is_connected():
                        continue
                    log.warning("client disconnected uid=%s; reconnecting", uid)
                    await client.connect()
                    if not await client.is_user_authorized():
                        log.error("client authorization expired uid=%s", uid)
                        await db.users.update_one({"_id": uid}, {"$set": {"dead": True}})
                        await self.kill(uid)
                        continue
                    log.info("reconnected uid=%s", uid)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("reconnect failed uid=%s; will retry", uid)
            await asyncio.sleep(30)


manager = Manager()
