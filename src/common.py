"""공용 설정/경로 로더."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "settings.yaml"
CONTENT_DIR = ROOT / "content"
OUTPUT_DIR = ROOT / "output"
STATE_FILE = ROOT / "state" / "log.json"
FONT_DIR = ROOT / "assets" / "fonts"


def load_settings() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_bank(track: str) -> list[dict]:
    path = CONTENT_DIR / f"bank_{track}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    for it in items:
        it.setdefault("track", track)
    return items


def load_all_items() -> list[dict]:
    return load_bank("A") + load_bank("B")


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"last_published_at": None, "published": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def published_slugs(state: dict | None = None) -> set[str]:
    state = state or load_state()
    return {p["slug"] for p in state.get("published", [])}


def load_dotenv(path: Path | None = None) -> None:
    """config/secrets.env 가 있으면 os.environ 에 로드(이미 설정된 값은 유지)."""
    path = path or (ROOT / "config" / "secrets.env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
