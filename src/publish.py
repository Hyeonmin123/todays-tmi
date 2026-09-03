"""Instagram API(Instagram 로그인 방식)로 글자 카드(캐러셀)를 발행한다.

필요 환경변수:
  IG_USER_ID       - Instagram 비즈니스 계정 ID (토큰 생성 화면에 표시된 숫자, 17841... 로 시작)
  IG_ACCESS_TOKEN  - Instagram 사용자 액세스 토큰 (IGAA... 로 시작, 60일 유효)

이미지 URL 은 인터넷에서 공개 접근 가능해야 한다(인스타 서버가 직접 내려받음).

CLI:
  python -m src.publish --urls URL1 URL2 --caption "..." --dry-run
"""
from __future__ import annotations

import argparse
import os
import time

import requests

from .common import load_dotenv, load_settings

# Instagram 로그인 방식은 graph.instagram.com 을 쓴다.
# (예전 Facebook 페이지 방식이면 settings.yaml 에서 api_base 를 graph.facebook.com 으로)
DEFAULT_BASE = "https://graph.instagram.com"


class PublishError(RuntimeError):
    pass


def _token() -> tuple[str, str]:
    load_dotenv()
    uid = os.environ.get("IG_USER_ID", "").strip()
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not uid or not tok:
        raise PublishError("IG_USER_ID / IG_ACCESS_TOKEN 환경변수가 필요합니다.")
    return uid, tok


def _post(url: str, data: dict, retries: int = 3) -> dict:
    delay = 2.0
    last = None
    for attempt in range(retries):
        r = requests.post(url, data=data, timeout=60)
        if r.status_code == 200:
            return r.json()
        last = f"HTTP {r.status_code}: {r.text}"
        # 일시 오류/레이트리밋만 재시도
        if r.status_code in (429, 500, 502, 503):
            time.sleep(delay)
            delay *= 2
            continue
        break
    raise PublishError(f"요청 실패: {url}\n{last}")


def _get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=60)
    if r.status_code != 200:
        raise PublishError(f"조회 실패 HTTP {r.status_code}: {r.text}")
    return r.json()


def _wait_ready(base: str, container_id: str, token: str, timeout: int = 120) -> None:
    """컨테이너가 FINISHED 될 때까지 대기(캐러셀 publish 전 권장)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = _get(f"{base}/{container_id}",
                    {"fields": "status_code,status", "access_token": token})
        code = info.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise PublishError(f"컨테이너 처리 실패: {info}")
        time.sleep(3)
    raise PublishError("컨테이너가 시간 내 준비되지 않음")


def publish_carousel(image_urls: list[str], caption: str,
                     cfg: dict | None = None, *, dry_run: bool = False) -> dict:
    cfg = cfg or load_settings()
    uid, token = _token()
    version = cfg.get("graph_api_version", "v21.0")
    api_base = cfg.get("api_base", DEFAULT_BASE).rstrip("/")
    root = f"{api_base}/{version}"
    base = f"{root}/{uid}"

    if not image_urls:
        raise PublishError("이미지 URL 이 없습니다.")

    # 단일 이미지
    if len(image_urls) == 1:
        cont = _post(f"{base}/media",
                     {"image_url": image_urls[0], "caption": caption, "access_token": token})
        container_id = cont["id"]
        result = {"type": "IMAGE", "container": container_id, "children": []}
    else:
        children = []
        for u in image_urls:
            c = _post(f"{base}/media",
                      {"image_url": u, "is_carousel_item": "true", "access_token": token})
            children.append(c["id"])
        cont = _post(f"{base}/media",
                     {"media_type": "CAROUSEL", "children": ",".join(children),
                      "caption": caption, "access_token": token})
        container_id = cont["id"]
        result = {"type": "CAROUSEL", "container": container_id, "children": children}

    if dry_run:
        result["dry_run"] = True
        return result

    _wait_ready(root, container_id, token)
    pub = _post(f"{base}/media_publish",
                {"creation_id": container_id, "access_token": token})
    media_id = pub["id"]
    permalink = None
    try:
        permalink = _get(f"{root}/{media_id}",
                         {"fields": "permalink", "access_token": token}).get("permalink")
    except PublishError:
        pass
    result.update({"media_id": media_id, "permalink": permalink})
    return result


def check_token(cfg: dict | None = None) -> dict:
    """토큰이 유효하고 IG_USER_ID 와 일치하는지 확인."""
    cfg = cfg or load_settings()
    uid, token = _token()
    api_base = cfg.get("api_base", DEFAULT_BASE).rstrip("/")
    version = cfg.get("graph_api_version", "v21.0")
    me = _get(f"{api_base}/{version}/me",
              {"fields": "user_id,username", "access_token": token})
    ok = str(me.get("user_id")) == str(uid)
    return {"me": me, "IG_USER_ID": uid, "match": ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="토큰 유효성 및 IG_USER_ID 일치 확인")
    ap.add_argument("--urls", nargs="+", help="공개 이미지 URL 목록")
    ap.add_argument("--caption", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="컨테이너만 만들고 실제 발행은 하지 않음")
    args = ap.parse_args()
    if args.check:
        r = check_token()
        print(r)
        print("OK" if r["match"] else "불일치: IG_USER_ID 와 토큰 계정이 다릅니다.")
        return
    if not args.urls:
        ap.error("--urls 가 필요합니다 (또는 --check).")
    res = publish_carousel(args.urls, args.caption, dry_run=args.dry_run)
    print(res)


if __name__ == "__main__":
    main()
