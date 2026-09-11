"""Editable rotating Discord presence configuration for Spectre."""

import os

DEFAULT_PRESENCE_MESSAGES = (
    "Spectre | /help",
    "حماية سيرفرك مع Spectre",
    "التذاكر والتقديمات بسهولة",
    "نظام اللفلات يعمل الآن",
)


def get_presence_messages(database=None) -> list[str]:
    if database is not None:
        try:
            saved = database.get_presence_config()
            if saved and saved.get("messages"):
                return list(saved["messages"])
        except Exception:
            pass
    raw = os.getenv("SPECTRE_PRESENCE_MESSAGES", "")
    messages = [item.strip()[:128] for item in raw.split("|") if item.strip()]
    return messages or list(DEFAULT_PRESENCE_MESSAGES)



def get_presence_interval(database=None) -> int:
    if database is not None:
        try:
            saved = database.get_presence_config()
            if saved:
                return max(15, min(int(saved.get("interval_seconds", 60)), 86400))
        except Exception:
            pass
    try:
        value = int(os.getenv("SPECTRE_PRESENCE_INTERVAL", "60"))
    except ValueError:
        value = 60
    return max(15, min(value, 86400))

