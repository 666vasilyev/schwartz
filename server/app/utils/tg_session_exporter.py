import json
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 1506593
API_HASH = "74b07d38a04337651c59ca46bb3e9ec6"

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()

    me = client.get_me()

    data = {
        "api_id": API_ID,
        "api_hash": API_HASH,
        "session_string": session_string,
        "phone": me.phone,
        "note": ""
    }

    print(json.dumps(data, indent=2, ensure_ascii=False))