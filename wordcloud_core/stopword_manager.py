import os
from typing import Optional

from .config import Config


class StopwordManager:
    def __init__(self, config: Config):
        self._config = config

    def _group_stopwords_path(self, group_key: str) -> str:
        return os.path.join(self._config.stopwords_dir, f"stopwords-{group_key}.txt")

    def _global_custom_path(self) -> str:
        return os.path.join(self._config.stopwords_dir, "custom-stopwords.txt")

    def add_word(self, word: str, group_key: Optional[str] = None) -> bool:
        if group_key:
            path = self._group_stopwords_path(group_key)
        else:
            path = self._global_custom_path()
        existing = self._load_words(path)
        if word in existing:
            return True
        existing.add(word)
        return self._save_words(path, existing)

    def remove_word(self, word: str, group_key: Optional[str] = None) -> bool:
        if group_key:
            path = self._group_stopwords_path(group_key)
        else:
            path = self._global_custom_path()
        existing = self._load_words(path)
        if word not in existing:
            return False
        existing.discard(word)
        if existing:
            return self._save_words(path, existing)
        else:
            if os.path.isfile(path):
                os.remove(path)
            return True

    def list_words(self, group_key: Optional[str] = None) -> list[str]:
        if group_key:
            path = self._group_stopwords_path(group_key)
        else:
            path = self._global_custom_path()
        return sorted(self._load_words(path))

    def load_group_stopwords(self, group_key: str) -> set:
        path = self._group_stopwords_path(group_key)
        return self._load_words(path)

    def load_global_custom_stopwords(self) -> set:
        path = self._global_custom_path()
        return self._load_words(path)

    def _load_words(self, path: str) -> set:
        if not os.path.isfile(path):
            return set()
        with open(path, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}

    def _save_words(self, path: str, words: set) -> bool:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for word in sorted(words):
                f.write(word + "\n")
        return True
