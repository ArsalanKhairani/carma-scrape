import os

import requests
from dotenv import load_dotenv

load_dotenv()

_HA_WEBHOOK_BASE = "http://homeassistant.local:8123/api/webhook/"
_NOTIFY_WEBHOOK_URL = _HA_WEBHOOK_BASE + os.environ["NOTIFY_WEBHOOK_ID"]


def notify(message: str, title: str = "") -> None:
    requests.post(_NOTIFY_WEBHOOK_URL, json={"message": message, "title": title}, timeout=10)
