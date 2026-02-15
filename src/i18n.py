"""ClipKeeper i18n helpers with JSON locale files."""

from __future__ import annotations

import json
import locale
import os
from typing import Any


APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES_DIR = os.path.join(APP_ROOT, "data", "locales")
SUPPORTED_LOCALES = ("en", "ru")
DEFAULT_LOCALE = "en"


class I18nManager:
    def __init__(self) -> None:
        self._translations: dict[str, dict[str, str]] = {}
        self._locale = DEFAULT_LOCALE

    def reload(self) -> None:
        self._translations.clear()
        for code in SUPPORTED_LOCALES:
            path = os.path.join(LOCALES_DIR, f"{code}.json")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._translations[code] = {
                        str(k): str(v) for k, v in data.items()
                    }
                else:
                    self._translations[code] = {}
            except (OSError, json.JSONDecodeError):
                self._translations[code] = {}

    def set_locale(self, value: str | None) -> str:
        if not value or value == "system":
            value = self.detect_system_locale()
        value = self._normalize_locale(value)
        self._locale = value
        return self._locale

    def get_locale(self) -> str:
        return self._locale

    def available_locales(self) -> tuple[str, ...]:
        return SUPPORTED_LOCALES

    def detect_system_locale(self) -> str:
        candidates = [
            os.environ.get("LC_ALL"),
            os.environ.get("LC_MESSAGES"),
            os.environ.get("LANG"),
        ]
        try:
            default_locale, _ = locale.getdefaultlocale()
            candidates.append(default_locale)
        except Exception:
            pass

        for candidate in candidates:
            normalized = self._normalize_locale(candidate)
            if normalized in SUPPORTED_LOCALES:
                return normalized
        return DEFAULT_LOCALE

    def tr(self, key: str, **kwargs: Any) -> str:
        text = (
            self._translations.get(self._locale, {}).get(key)
            or self._translations.get(DEFAULT_LOCALE, {}).get(key)
            or key
        )
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    @staticmethod
    def _normalize_locale(value: str | None) -> str:
        if not value:
            return DEFAULT_LOCALE
        lowered = str(value).strip().lower().replace("-", "_")
        if lowered.startswith("ru"):
            return "ru"
        if lowered.startswith("en"):
            return "en"
        return DEFAULT_LOCALE


_MANAGER = I18nManager()
_MANAGER.reload()
_MANAGER.set_locale("system")


def set_locale(value: str | None) -> str:
    return _MANAGER.set_locale(value)


def get_locale() -> str:
    return _MANAGER.get_locale()


def available_locales() -> tuple[str, ...]:
    return _MANAGER.available_locales()


def reload_locales() -> None:
    _MANAGER.reload()


def tr(key: str, **kwargs: Any) -> str:
    return _MANAGER.tr(key, **kwargs)
