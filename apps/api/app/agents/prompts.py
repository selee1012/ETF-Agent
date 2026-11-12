"""prompts/ 디렉터리 로더. 설정 PROMPTS_DIR 기준 상대 경로로 읽는다."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.settings import get_settings


def _root() -> Path:
    return get_settings().prompts_dir


@lru_cache(maxsize=128)
def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_text(rel: str) -> str:
    return _read(str(_root() / rel)).strip()


def load_yaml(rel: str) -> dict[str, Any]:
    return yaml.safe_load(_read(str(_root() / rel))) or {}


def render_template(rel: str, **values: str) -> str:
    text = load_text(rel)
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def clear_cache() -> None:
    _read.cache_clear()
