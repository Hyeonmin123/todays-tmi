"""문구 큐가 적게 남으면 GitHub 이슈로 알림."""
from __future__ import annotations

import os

import requests

from .common import load_dotenv

TITLE_PREFIX = "[별] 문구 뱅크 보충 필요"


def notify_low_queue(rem: dict) -> None:
    load_dotenv()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    token = token.strip()
    msg = (f"남은 문구: A {rem['A']} / B {rem['B']} / 합계 {rem['total']}\n\n"
           f"`content/bank_A.json`, `content/bank_B.json` 아래쪽에 항목을 추가하고 push 하세요.\n"
           f"형식은 `content/SCHEMA.md` 참고.")
    if not repo or not token:
        print(f"[알림] {TITLE_PREFIX} — {msg}")
        return

    api = f"https://api.github.com/repos/{repo}/issues"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    # 이미 열린 동일 이슈가 있으면 중복 생성 안 함
    try:
        existing = requests.get(api, headers=headers,
                                params={"state": "open", "per_page": 100}, timeout=30)
        if existing.status_code == 200 and any(
                i["title"].startswith(TITLE_PREFIX) for i in existing.json()):
            print("이미 열린 보충 이슈가 있어 생성하지 않음.")
            return
    except requests.RequestException:
        pass

    title = f"{TITLE_PREFIX} (남은 {rem['total']}개)"
    r = requests.post(api, headers=headers, json={"title": title, "body": msg}, timeout=30)
    if r.status_code in (200, 201):
        print(f"이슈 생성: {r.json().get('html_url')}")
    else:
        print(f"이슈 생성 실패 HTTP {r.status_code}: {r.text}")
