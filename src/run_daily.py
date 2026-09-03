"""매일 실행되는 오케스트레이터.

흐름:
  1. 오늘 발행 목표(target_today) 대비 오늘 이미 올린 개수를 비교. 다 채웠으면 종료.
     (부스트 기간이면 boost_per_day 개, 아니면 interval_days 마다 1개)
  2. 큐에서 다음 문구 선택. 없으면 알림 후 종료.
  3. 카드 PNG 렌더 -> output/<날짜>_<slug>/
  4. (Actions) 이미지 커밋 & push  -> raw.githubusercontent.com URL 확보
  5. Instagram Graph API 로 캐러셀 발행
  6. state/log.json 갱신 & push
  7. 남은 문구가 임계치 미만이면 GitHub 이슈 알림

옵션:
  --dry-run   렌더까지만. git/발행 없음. URL 은 가정해서 출력.
  --no-git    git 커밋/푸시 생략(로컬에서 발행만 테스트).
  --force     발행일이 아니어도 강제 실행.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

from . import notify
from .common import OUTPUT_DIR, ROOT, load_dotenv, load_settings, load_state, save_state
from .publish import publish_carousel
from .queue import pick_next, remaining

KST = dt.timezone(dt.timedelta(hours=9))


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def _posts_today(state: dict) -> int:
    today = today_kst().isoformat()
    return sum(1 for p in state.get("published", [])
               if str(p.get("published_at", ""))[:10] == today)


def _hours_since_last(state: dict) -> float:
    pub = state.get("published", [])
    if not pub:
        return 1e9
    try:
        last = dt.datetime.fromisoformat(pub[-1]["published_at"])
    except (KeyError, ValueError):
        return 1e9
    return (dt.datetime.now(KST) - last).total_seconds() / 3600


def target_today(state: dict, cfg: dict) -> int:
    """오늘 발행해야 할 총 개수.
    - boost_until(포함) 이전이면 boost_per_day 개
    - 그 외에는 interval_days 마다 1개
    """
    today = today_kst()
    boost_until = cfg.get("boost_until")
    if boost_until and today <= dt.date.fromisoformat(str(boost_until)[:10]):
        return int(cfg.get("boost_per_day", 1))
    last = state.get("last_published_at")
    if not last:
        return 1
    gap = (today - dt.date.fromisoformat(str(last)[:10])).days
    return 1 if gap >= int(cfg.get("interval_days", 1)) else 0


def _run(cmd: list[str]) -> str:
    print("  $", " ".join(cmd))
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if out.stdout.strip():
        print("   ", out.stdout.strip().replace("\n", "\n    "))
    if out.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd)}\n{out.stderr}")
    return out.stdout.strip()


def _git_config_if_needed() -> None:
    have = subprocess.run(["git", "config", "user.email"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    if not have:
        _run(["git", "config", "user.email", "actions@users.noreply.github.com"])
        _run(["git", "config", "user.name", "byeol-bot"])


def git_commit_push(paths: list[str], message: str) -> None:
    _git_config_if_needed()
    _run(["git", "add", *paths])
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    if not status:
        print("  (변경 없음, 커밋 생략)")
        return
    _run(["git", "commit", "-m", message])
    _run(["git", "push"])


def _repo_from_git() -> str:
    """git origin URL 에서 'owner/repo' 추출 (로컬 실행용)."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""
    if not url:
        return ""
    url = url.removesuffix(".git")
    if url.startswith("git@"):          # git@github.com:owner/repo
        url = url.split(":", 1)[-1]
    else:                               # https://github.com/owner/repo
        url = "/".join(url.split("/")[-2:])
    return url


def raw_base() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip() or _repo_from_git()
    branch = (os.environ.get("GITHUB_REF_NAME", "").strip()
              or subprocess.run(["git", "branch", "--show-current"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
              or "main")
    if not repo:
        repo = "USER/REPO"
    return f"https://raw.githubusercontent.com/{repo}/{branch}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    load_dotenv()
    cfg = load_settings()
    state = load_state()

    if not args.force and not args.dry_run:
        want = target_today(state, cfg)
        have = _posts_today(state)
        if have >= want:
            print(f"오늘({today_kst()}) 발행 목표 {want}개 중 {have}개 완료 → 스킵.")
            return 0
        min_gap = float(cfg.get("min_hours_between_posts", 0))
        since = _hours_since_last(state)
        if since < min_gap:
            print(f"직전 발행에서 {since:.1f}시간 경과 (최소 {min_gap}시간) → 스킵.")
            return 0
        print(f"오늘({today_kst()}) 발행 {have}/{want} → 1개 진행.")

    item = pick_next(state, cfg)
    if not item:
        print("큐가 비어 있음. 문구를 추가하세요.")
        notify.notify_low_queue(remaining(state))
        return 0

    print(f"발행 대상: [{item['track']}] {item['slug']}")

    # 3. 렌더
    from .render import render_item
    date_str = today_kst().isoformat()
    out_dir = OUTPUT_DIR / f"{date_str}_{item['slug']}"
    paths = render_item(item, out_dir, cfg)
    rel_paths = [p.relative_to(ROOT).as_posix() for p in paths]
    print("렌더 완료:", *rel_paths, sep="\n  ")

    caption = item["caption"].rstrip()
    if item.get("source"):
        caption += "\n\n" + item["source"]
    # 항목별 태그 5개 + (초반 한정) 그날 주제 관련 태그 5개. 중복 제거(대소문자 무시).
    pool = list(item.get("hashtags", []))
    if len(state.get("published", [])) < int(cfg.get("extra_hashtags_until_post", 0)):
        pool += list(item.get("extra_hashtags", []))
    tags: list[str] = []
    seen: set[str] = set()
    for t in pool:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            tags.append(t)
    caption += "\n\n" + " ".join(tags)
    urls = [f"{raw_base()}/{rp}" for rp in rel_paths]

    if args.dry_run:
        print("\n[DRY-RUN] 발행하지 않음. 예상 이미지 URL:")
        for u in urls:
            print("  ", u)
        print("\n[DRY-RUN] 캡션:\n" + caption)
        return 0

    # 4. 이미지 먼저 커밋/푸시 (raw URL 이 살아있어야 인스타가 받아감)
    if not args.no_git:
        git_commit_push([out_dir.relative_to(ROOT).as_posix()],
                        f"post: render {item['slug']} ({date_str})")
        print("raw CDN 반영 대기...")
        time.sleep(12)

    # 5. 발행
    res = publish_carousel(urls, caption, cfg)
    print("발행 결과:", res)

    # 6. 상태 갱신
    state.setdefault("published", []).append({
        "slug": item["slug"],
        "track": item["track"],
        "published_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "media_id": res.get("media_id"),
        "permalink": res.get("permalink"),
    })
    state["last_published_at"] = date_str
    save_state(state)
    if not args.no_git:
        git_commit_push(["state/log.json"], f"post: mark published {item['slug']} ({date_str})")

    # 7. 큐 소진 알림
    rem = remaining(state)
    print(f"남은 문구: A {rem['A']} / B {rem['B']} / 합계 {rem['total']}")
    if rem["total"] < int(cfg.get("low_queue_threshold", 5)):
        notify.notify_low_queue(rem)

    print("완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
