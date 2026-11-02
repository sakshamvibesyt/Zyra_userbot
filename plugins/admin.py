"""Reply-based group moderation helpers. Telegram permissions are enforced by Telegram."""
import html
import re

from telethon import events
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights, ChannelParticipantAdmin, ChannelParticipantCreator
from telethon.errors import ChatAdminRequiredError, UserAdminInvalidError


def setup(client):
    p = re.escape(client.prefix)

    async def target_from_reply(e):
        reply = await e.get_reply_message()
        if not reply:
            return None, "Reply to the user's message first."
        try:
            user = await reply.get_sender()
        except Exception:
            user = None
        if not user:
            return None, "Could not identify that user."
        return user, None

    async def run_action(e, action):
        reply = await e.get_reply_message()
        if action in ("pin", "unpin"):
            try:
                if action == "pin":
                    if not reply:
                        return await e.edit("Reply to the message you want to pin.")
                    await client.pin_message(e.chat_id, reply, notify=False)
                    return await e.edit("Pinned.")
                await client.unpin_message(e.chat_id)
                return await e.edit("Unpinned latest pinned message.")
            except Exception as ex:
                return await e.edit("Action failed: <code>%s</code>" % html.escape(str(ex)[:180]))
        user, error = await target_from_reply(e)
        if error:
            return await e.edit(error)
        try:
            if action == "ban":
                await client(EditBannedRequest(e.chat_id, user.id, ChatBannedRights(until_date=None, view_messages=True)))
                msg = "Banned"
            elif action == "unban":
                await client(EditBannedRequest(e.chat_id, user.id, ChatBannedRights(until_date=None)))
                msg = "Unbanned"
            elif action == "mute":
                await client(EditBannedRequest(e.chat_id, user.id, ChatBannedRights(until_date=None, send_messages=True, send_media=True, send_stickers=True, send_gifs=True)))
                msg = "Muted"
            elif action == "unmute":
                await client(EditBannedRequest(e.chat_id, user.id, ChatBannedRights(until_date=None)))
                msg = "Unmuted"
            elif action == "kick":
                await client(EditBannedRequest(e.chat_id, user.id, ChatBannedRights(until_date=None, view_messages=True)))
                await client(EditBannedRequest(e.chat_id, user.id, ChatBannedRights(until_date=None)))
                msg = "Kicked"
            elif action == "del":
                await client.delete_messages(e.chat_id, [e.id, (await e.get_reply_message()).id])
                return
            else:
                return
            await e.edit("%s: <b>%s</b> (<code>%s</code>)" % (msg, html.escape(getattr(user, "first_name", None) or "user"), user.id))
        except (ChatAdminRequiredError, UserAdminInvalidError):
            await e.edit("Action failed: I need the required admin rights, or the target has higher permissions.")
        except Exception as ex:
            await e.edit("Action failed: <code>%s</code>" % html.escape(str(ex)[:180]))

    for action in ("ban", "unban", "mute", "unmute", "kick", "del", "pin", "unpin"):
        @client.on(events.NewMessage(pattern=r"^" + p + action + r"$", outgoing=True))
        async def handler(e, _action=action):
            await run_action(e, _action)

    @client.on(events.NewMessage(pattern=r"^" + p + r"purge(?:\s+(\d+))?$", outgoing=True))
    async def purge(e):
        count = min(int(e.pattern_match.group(1) or 20), 100)
        try:
            messages = await client.get_messages(e.chat_id, limit=count)
            ids = [m.id for m in messages]
            ids.append(e.id)
            await client.delete_messages(e.chat_id, ids)
        except Exception as ex:
            await e.edit("Purge failed: <code>%s</code>" % html.escape(str(ex)[:180]))

    @client.on(events.NewMessage(pattern=r"^" + p + r"adminhelp$", outgoing=True))
    async def adminhelp(e):
        await e.edit(
            "<b>ZYRA · ADMIN TOOLS</b>\n\n"
            "Reply to a user's message: <code>.ban</code>, <code>.unban</code>, "
            "<code>.mute</code>, <code>.unmute</code>, <code>.kick</code>, <code>.del</code>.\n"
            "Reply to a message: <code>.pin</code> · <code>.purge 20</code> · <code>.id</code>.\n"
            "Other: <code>.unpin</code> · <code>.admins</code>.\n\n"
            "Telegram must grant your account the required admin permissions."
        )

    @client.on(events.NewMessage(pattern=r"^" + p + r"id$", outgoing=True))
    async def ids(e):
        reply = await e.get_reply_message()
        if reply:
            await e.edit("Chat ID: <code>%s</code>\nUser ID: <code>%s</code>" % (e.chat_id, reply.sender_id))
        else:
            await e.edit("Chat ID: <code>%s</code>\nYour ID: <code>%s</code>" % (e.chat_id, client.me_id))

    @client.on(events.NewMessage(pattern=r"^" + p + r"admins$", outgoing=True))
    async def admins(e):
        try:
            participants = await client.get_participants(e.chat_id, filter=None)
            lines = []
            for part in participants:
                participant = getattr(part, "participant", None)
                if isinstance(participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                    lines.append("• %s — <code>%s</code>" % (html.escape(getattr(part, "first_name", None) or "user"), part.id))
            await e.edit("<b>Admins</b>\n" + ("\n".join(lines[:50]) if lines else "No admins found."))
        except Exception as ex:
            await e.edit("Could not list admins: <code>%s</code>" % html.escape(str(ex)[:180]))
