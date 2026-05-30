import json
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 12345678
API_HASH = "your_api_hash"

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