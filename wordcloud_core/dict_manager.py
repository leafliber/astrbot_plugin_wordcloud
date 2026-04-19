import os
from typing import Optional

from .config import Config


class DictManager:
    def __init__(self, config: Config):
        self._config = config

    def _group_dict_path(self, group_key: str) -> str:
        return os.path.join(self._config.dict_dir, f"dict-{group_key}.txt")

    def add_word(self, group_key: str, word: str, pos: Optional[str] = None) -> bool:
        path = self._group_dict_path(group_key)
        existing = self._load_words(path)

        entry = word if pos is None else f"{word} {pos}"
        if word in existing:
            existing[word] = entry
        else:
            existing[word] = entry

        return self._save_words(path, existing)

    def remove_word(self, group_key: str, word: str) -> bool:
        path = self._group_dict_path(group_key)
        existing = self._load_words(path)
        if word not in existing:
            return False
        del existing[word]
        if existing:
            return self._save_words(path, existing)
        else:
            if os.path.isfile(path):
                os.remove(path)
            return True

    def list_words(self, group_key: str) -> list[str]:
        path = self._group_dict_path(group_key)
        existing = self._load_words(path)
        return list(existing.values())

    def _load_words(self, path: str) -> dict[str, str]:
        if not os.path.isfile(path):
            return {}
        result = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                word = parts[0]
                result[word] = line
        return result

    def _save_words(self, path: str, words: dict[str, str]) -> bool:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for entry in words.values():
                f.write(entry + "\n")
        return True
