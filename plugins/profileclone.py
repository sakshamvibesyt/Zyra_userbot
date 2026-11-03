"""MyTron-style profile clone/revert commands adapted for Zyra's Telethon client.

Usage: reply to a user's message with .clone, or use .clone @username.
Only use profile copying with the person's permission; do not impersonate others.
"""
import html
import os
import re
import tempfile

from telethon import events, functions, utils
import db as database


def setup(client):
    p = re.escape(client.prefix)
    uid = client.uid
    backups = database.db.zyra_profile_backups

    async def get_about(entity):
        full = await client(functions.users.GetFullUserRequest(id=entity))
        return getattr(full.full_user, 'about', '') or ''

    async def download_photo(photo):
        path = None
        try:
            with tempfile.NamedTemporaryFile(prefix='zyra_profile_', suffix='.jpg', delete=False) as f:
                path = f.name
            result = await client.download_media(photo, file=path)
            if not result or not os.path.exists(path) or os.path.getsize(path) == 0:
                return None
            with open(path, 'rb') as f:
                return f.read()
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    async def get_photos(entity, limit=5):
        photos = await client.get_profile_photos(entity, limit=limit)
        output = []
        # Telegram returns newest first; reverse to upload oldest-to-newest like MyTron.
        for photo in reversed(list(photos)):
            data = await download_photo(photo)
            if data:
                output.append(data)
        return output

    async def clear_photos():
        photos = await client.get_profile_photos('me', limit=100)
        if photos:
            await client(functions.photos.DeletePhotosRequest(
                id=[utils.get_input_photo(photo) for photo in photos]
            ))

    async def set_photos(photo_data):
        await clear_photos()
        for data in photo_data or []:
            path = None
            try:
                with tempfile.NamedTemporaryFile(prefix='zyra_profile_upload_', suffix='.jpg', delete=False) as f:
                    f.write(data)
                    path = f.name
                uploaded = await client.upload_file(path)
                await client(functions.photos.UploadProfilePhotoRequest(file=uploaded))
            finally:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    async def save_original_once(me):
        existing = await backups.find_one({'uid': uid, 'had_backup': True})
        if existing:
            return
        await backups.insert_one({
            'uid': uid,
            'first_name': me.first_name or '',
            'last_name': me.last_name or '',
            'about': await get_about(me),
            'photos': await get_photos('me', limit=5),
            'had_backup': True,
        })

    @client.on(events.NewMessage(pattern=r'^' + p + r'clone(?:\s+@?([A-Za-z0-9_]{5,32}))?\s*$', outgoing=True))
    async def clone_profile(e):
        username = e.pattern_match.group(1)
        try:
            if username:
                target = await client.get_entity(username)
            elif e.is_reply:
                replied = await e.get_reply_message()
                if not replied or not replied.sender_id:
                    return await e.edit('Jis user ka profile clone karna hai, uske message par reply karke <code>.clone</code> bhejo.')
                target = await replied.get_sender()
            else:
                return await e.edit('Kisi user ke message par reply karke <code>.clone</code> bhejo, ya <code>.clone @username</code> use karo.')

            me = await client.get_me()
            if target.id == me.id:
                return await e.edit('Ye tumhara hi profile hai. Kisi doosre authorized profile ko select karo.')

            await e.edit('✦ <b>Profile clone ho raha hai...</b>')
            await save_original_once(me)
            target_photos = await get_photos(target, limit=5)
            target_about = await get_about(target)

            await client(functions.account.UpdateProfileRequest(
                first_name=(getattr(target, 'first_name', None) or ' '),
                last_name=(getattr(target, 'last_name', None) or ''),
                about=target_about,
            ))
            await set_photos(target_photos)
            await e.edit(
                '✦ <b>Profile clone complete!</b>\n'
                'Name, bio aur available profile photos apply ho gaye.\n'
                'Original profile ke liye <code>.reclone</code> ya <code>.revert</code> use karo.\n\n'
                '<i>Sirf permission ke saath use karo; kisi ki identity ban kar mislead mat karo.</i>'
            )
        except Exception as ex:
            msg = html.escape(str(ex))[:180]
            await e.edit('Profile clone nahi hua: <code>%s</code>' % msg)

    @client.on(events.NewMessage(pattern=r'^' + p + r'(?:reclone|revert)\s*$', outgoing=True))
    async def restore_profile(e):
        backup = await backups.find_one({'uid': uid, 'had_backup': True})
        if not backup:
            return await e.edit('Original profile ka backup nahi mila. Pehle <code>.clone</code> use karo.')
        try:
            await e.edit('✦ <b>Original profile restore ho raha hai...</b>')
            await client(functions.account.UpdateProfileRequest(
                first_name=backup.get('first_name') or ' ',
                last_name=backup.get('last_name') or '',
                about=backup.get('about') or '',
            ))
            photos = backup.get('photos')
            if photos is None:  # support backups created by the older Zyra plugin
                old_photo = backup.get('photo')
                photos = [old_photo] if old_photo else []
            await set_photos(photos)
            await backups.delete_one({'_id': backup['_id']})
            await e.edit('✓ <b>Original profile restored.</b> Name, bio aur saved photos wapas aa gaye.')
        except Exception as ex:
            msg = html.escape(str(ex))[:180]
            await e.edit('Restore nahi hua: <code>%s</code>' % msg)
