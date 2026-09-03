"""발행 큐: 다음에 올릴 문구 항목을 고른다.

- bank_A.json + bank_B.json 을 위에서부터 순서대로 소비.
- state/log.json 에 기록된 slug 는 건너뜀.
- rotation(예: [A,A,A,B]) 에 따라 트랙을 번갈아 고르고,
  해당 트랙에 남은 항목이 없으면 다른 트랙으로 대체.
"""
from __future__ import annotations

import argparse

from .common import load_bank, load_settings, load_state, published_slugs


def _unpublished(track: str, done: set[str]) -> list[dict]:
    return [it for it in load_bank(track) if it["slug"] not in done]


def remaining(state: dict | None = None) -> dict:
    done = published_slugs(state)
    a, b = _unpublished("A", done), _unpublished("B", done)
    return {"A": len(a), "B": len(b), "total": len(a) + len(b)}


def next_track(state: dict, cfg: dict) -> str:
    rotation = [str(t).upper() for t in cfg.get("rotation", ["A"])]
    n = len(state.get("published", []))
    return rotation[n % len(rotation)]


def pick_next(state: dict | None = None, cfg: dict | None = None) -> dict | None:
    state = state if state is not None else load_state()
    cfg = cfg or load_settings()
    done = published_slugs(state)
    want = next_track(state, cfg)
    order = [want] + [t for t in ("A", "B") if t != want]
    for track in order:
        pool = _unpublished(track, done)
        if pool:
            return pool[0]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.parse_args()

    cfg = load_settings()
    state = load_state()
    rem = remaining(state)
    nxt = pick_next(state, cfg)
    print(f"발행 이력      : {len(state.get('published', []))}건")
    print(f"마지막 발행일  : {state.get('last_published_at')}")
    print(f"다음 트랙(rotation): {next_track(state, cfg)}")
    print(f"남은 문구      : A {rem['A']} / B {rem['B']} / 합계 {rem['total']}")
    if nxt:
        n_items = len(nxt.get("body", {}).get("items", [])) or 1
        print(f"다음 발행 예정 : [{nxt['track']}] {nxt['slug']}  (본문 {n_items}줄)")
        print(f"  제목: {nxt.get('title', '').replace(chr(10), ' ')!r}")
    else:
        print("다음 발행 예정 : (큐 비어 있음 — 문구 추가 필요)")
    if rem["total"] < cfg.get("low_queue_threshold", 5):
        print(f"\n[경고] 남은 문구가 {rem['total']}개뿐. bank_A.json / bank_B.json 에 추가하세요.")


if __name__ == "__main__":
    main()
