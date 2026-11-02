"""Authorized profile template apply/restore commands for Zyra Userbot.

For privacy and anti-impersonation, only usernames explicitly listed in
CLONE_ALLOWED_USERNAMES may be used as profile sources.
"""
import os
import re
import tempfile

from telethon import events, functions, utils
import db as database


def setup(client):
    p = re.escape(client.prefix)
    uid = client.uid
    backups = database.db.zyra_profile_backups
    allowed = {
        x.strip().lstrip('@').casefold()
        for x in os.environ.get('CLONE_ALLOWED_USERNAMES', '').split(',')
        if x.strip()
    }

    async def get_about(entity):
        full = await client(functions.users.GetFullUserRequest(id=entity))
        return getattr(full.full_user, 'about', '') or ''

    async def photo_bytes(entity):
        path = None
        try:
            with tempfile.NamedTemporaryFile(prefix='zyra_profile_', suffix='.jpg', delete=False) as f:
                path = f.name
            result = await client.download_profile_photo(entity, file=path)
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

    async def apply_photo(data):
        if not data:
            # Remove the current profile photo when the saved original had none.
            photos = await client.get_profile_photos('me', limit=1)
            if photos:
                await client(functions.photos.DeletePhotosRequest(id=[utils.get_input_photo(photos[0])]))
            return
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

    @client.on(events.NewMessage(pattern=r'^' + p + r'clone\s+@?([A-Za-z0-9_]{5,32})\s*$', outgoing=True))
    async def clone_profile(e):
        username = e.pattern_match.group(1).casefold()
        if username not in allowed:
            return await e.edit(
                '<b>Profile source not allowed.</b>\n'
                'Sirf apni ya permission wali profile use karo. Authorized username ko '
                '<code>CLONE_ALLOWED_USERNAMES</code> environment variable mein add karo '
                '(comma-separated), phir redeploy karo.'
            )
        try:
            target = await client.get_entity(username)
            me = await client.get_me()
            current_about = await get_about(me)
            current_photo = await photo_bytes(me)
            # Save the original profile only once, so repeated .clone calls do not
            # overwrite the profile that .reclone is supposed to restore.
            await backups.update_one(
                {'uid': uid},
                {'$setOnInsert': {
                    'first_name': me.first_name or '',
                    'last_name': me.last_name or '',
                    'about': current_about,
                    'photo': current_photo,
                    'had_backup': True,
                }},
                upsert=True,
            )
            target_photo = await photo_bytes(target)
            await client(functions.account.UpdateProfileRequest(
                first_name=(getattr(target, 'first_name', None) or ' '),
                last_name=(getattr(target, 'last_name', None) or ''),
                about=await get_about(target),
            ))
            if target_photo:
                await apply_photo(target_photo)
            else:
                await apply_photo(None)
            await e.edit(
                '<b>✦ Profile template applied</b>\n'
                'Name, bio aur photo update kar diye gaye.\n'
                '<code>.reclone</code> se saved original profile restore kar sakte ho.'
            )
        except Exception as ex:
            await e.edit('Profile apply nahi hua: <code>%s</code>' % str(ex).replace('<', '&lt;').replace('>', '&gt;')[:180])

    @client.on(events.NewMessage(pattern=r'^' + p + r'reclone$', outgoing=True))
    async def restore_profile(e):
        backup = await backups.find_one({'uid': uid, 'had_backup': True})
        if not backup:
            return await e.edit('Original profile ka backup nahi mila. Pehle authorized <code>.clone @username</code> use karo.')
        try:
            await client(functions.account.UpdateProfileRequest(
                first_name=backup.get('first_name') or ' ',
                last_name=backup.get('last_name') or '',
                about=backup.get('about') or '',
            ))
            await apply_photo(backup.get('photo'))
            await backups.delete_one({'uid': uid})
            await e.edit('<b>✓ Original profile restored.</b> Name, bio aur photo wapas aa gaye.')
        except Exception as ex:
            await e.edit('Restore nahi hua: <code>%s</code>' % str(ex).replace('<', '&lt;').replace('>', '&gt;')[:180])
