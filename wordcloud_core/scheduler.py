import json
import os
from typing import Optional

from astrbot.api.star import StarTools

_PLUGIN_DIR_NAME = "astrbot_plugin_wordcloud"
_SCHEDULE_FILE = "schedules.json"


def _get_schedule_path() -> str:
    data_dir = StarTools.get_data_dir(_PLUGIN_DIR_NAME)
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / _SCHEDULE_FILE)


def load_schedules() -> dict:
    path = _get_schedule_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_schedules(schedules: dict) -> None:
    path = _get_schedule_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schedules, f, ensure_ascii=False, indent=2)


def add_schedule(
    group_key: str,
    time_str: str,
    unified_msg_origin: str = "",
    group_id: str = "",
) -> None:
    schedules = load_schedules()
    schedules[group_key] = {
        "time": time_str,
        "enabled": True,
        "umo": unified_msg_origin,
        "group_id": group_id,
    }
    save_schedules(schedules)


def remove_schedule(group_key: str) -> bool:
    schedules = load_schedules()
    if group_key not in schedules:
        return False
    del schedules[group_key]
    save_schedules(schedules)
    return True


def get_schedule(group_key: str) -> Optional[dict]:
    schedules = load_schedules()
    return schedules.get(group_key)


def get_all_schedules() -> dict:
    return load_schedules()
