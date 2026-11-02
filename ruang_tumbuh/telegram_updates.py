"""Keep only fields required to process a private text message."""

import re


def normalize_private_update(update):
    update_id = update.get('update_id')
    callback = update.get('callback_query')
    message = update.get('message')
    callback_id = None
    if callback is not None:
        if not isinstance(callback, dict) or not isinstance(callback.get('message'), dict):
            return None
        original = callback['message']
        action = re.fullmatch(r'(save|cancel):(\d{1,19})', callback.get('data', ''))
        choose = re.fullmatch(r'choose:(\d{1,19}):(\d{1,19})', callback.get('data', ''))
        edit = re.fullmatch(r'editdraft:(\d{1,19})', callback.get('data', ''))
        if not (action or choose or edit) or not isinstance(callback.get('id'), str) or len(callback['id']) > 256:
            return None
        callback_id = callback['id']
        text = (('simpan ' if action[1] == 'save' else 'batal ') + action[2]) if action else f'/pilih {choose[1]} {choose[2]}' if choose else 'ubah ' + edit[1]
        message = {'chat': original.get('chat'), 'date': original.get('date'), 'from': callback.get('from'),
                   'text': text}
    if not isinstance(message, dict) or not isinstance(message.get('chat'), dict) or message['chat'].get('type') != 'private':
        return None
    sender = message.get('from')
    user = sender.get('id') if isinstance(sender, dict) else None
    text, date = message.get('text'), message.get('date')
    if (type(update_id) is not int or update_id < 0 or type(user) is not int or not 0 < user < 2**52
            or message['chat'].get('id') != user or sender.get('is_bot') is True
            or not isinstance(text, str) or len(text) > 4096 or type(date) is not int or date <= 0):
        raise ValueError('Invalid private update')
    result = minimal_private_update(update_id, user, text, date)
    if callback_id is not None:
        result['callback_id'] = callback_id
    return result


def minimal_private_update(update_id, user_id, text, message_date):
    return {
        'update_id': update_id,
        'message': {
            'date': message_date,
            'text': text,
            'chat': {'id': user_id, 'type': 'private'},
            'from': {'id': user_id, 'is_bot': False},
        },
    }

