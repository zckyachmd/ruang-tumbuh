"""Keep only fields required to process a private text message."""


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
