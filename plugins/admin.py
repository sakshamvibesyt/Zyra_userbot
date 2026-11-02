from telethon import events
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights


def setup(client):
    p = client.prefix

    async def sender(e):
        r = await e.get_reply_message()
        return await r.get_sender() if r else None

    @client.on(events.NewMessage(pattern=r"^" + p + r"ban", outgoing=True))
    async def ban(e):
        u = await sender(e)
        if not u:
            return await e.edit("kisi ke message pe reply karo")
        await client(EditBannedRequest(
            e.chat_id, u.id, ChatBannedRights(until_date=None, view_messages=True)
        ))
        await e.edit("banned " + str(u.first_name))

    @client.on(events.NewMessage(pattern=r"^" + p + r"unban", outgoing=True))
    async def unban(e):
        u = await sender(e)
        if not u:
            return await e.edit("reply karo")
        await client(EditBannedRequest(
            e.chat_id, u.id, ChatBannedRights(until_date=None)
        ))
        await e.edit("unbanned " + str(u.first_name))

    @client.on(events.NewMessage(pattern=r"^" + p + r"purge(?:\s+(\d+))?", outgoing=True))
    async def purge(e):
        n = int(e.pattern_match.group(1) or 20) + 1
        msgs = await client.get_messages(e.chat_id, limit=n)
        await client.delete_messages(e.chat_id, msgs)
