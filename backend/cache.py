"""
File cache keyed by a hash of the claim, so the same claim always yields the same cards.
That is what makes results reproducible. One JSON file is enough for this prototype.
"""
import hashlib
import json
import os
import threading

CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache_store.json")
_lock = threading.Lock()


def claim_key(statement: str) -> str:
    norm = "".join(statement.lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _load() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def get(key: str):
    with _lock:
        return _load().get(key)


def put(key: str, value: dict) -> None:
    with _lock:
        data = _load()
        data[key] = value
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
