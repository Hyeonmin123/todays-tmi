"""Instagram 사용자 액세스 토큰(IGAA...) 갱신.

Instagram 로그인 방식의 장기 토큰은 60일 유효하고, 만료 전에 갱신하면 다시 60일 연장된다.
(발급 후 24시간이 지난 토큰이어야 갱신 가능)

필요 환경변수: IG_ACCESS_TOKEN (현재 토큰)

출력된 새 토큰을 GitHub 저장소 Secret(IG_ACCESS_TOKEN)에 직접 교체하세요.
자동화하려면 이 스크립트를 월 1회 워크플로로 돌리고, gh CLI 로 Secret 을 갱신하면 된다.
"""
from __future__ import annotations

import os

import requests

from .common import load_dotenv, load_settings
from .publish import DEFAULT_BASE


def main() -> None:
    load_dotenv()
    cfg = load_settings()
    api_base = cfg.get("api_base", DEFAULT_BASE).rstrip("/")
    cur = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not cur:
        raise SystemExit("IG_ACCESS_TOKEN 환경변수가 필요합니다.")

    r = requests.get(
        f"{api_base}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": cur},
        timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit(f"갱신 실패 HTTP {r.status_code}: {r.text}")
    data = r.json()
    days = int(data.get("expires_in", 0)) // 86400
    print("새 토큰:")
    print(data["access_token"])
    print(f"\n유효기간: 약 {days}일")
    print("→ GitHub 저장소 Settings > Secrets and variables > Actions 의 "
          "IG_ACCESS_TOKEN 값을 위 토큰으로 교체하세요.")


if __name__ == "__main__":
    main()
