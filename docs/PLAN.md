# 인스타그램 "글자 콘텐츠" 자동 발행 파이프라인 (프로젝트: 별)

## Context

사용자는 인스타그램 인플루언서를 목표로, **글자만 있는 이미지 + 캡션** 게시물을
**하루 1개 ~ 3일 1개** 페이스로 자동 발행하고 싶어 한다. 지금은 작업 폴더
`E:\개인\별` 가 비어 있고(코드 없음), Python 3.13(Anaconda) + pip 사용 가능.

트렌드 조사 결과 반영:
- 2026년 알고리즘은 **일관된 한 주제** + **저장/공유/프로필 방문으로 이어지는 콘텐츠**를 우대.
- 릴스 도달은 감소, **카드뉴스(캐러셀) 저장 수는 2~3배 증가**. 팔로워 대비 참여율은 캐러셀 우위.
- AI 콘텐츠 범람 → **본인 관점으로 쓴 문장**이 살아남음. 캡처 짜깁기·재게시는 불이익.
- 검색화: 캡션 첫 문장·이미지 속 글자·대체텍스트에 **"누구의 어떤 고민"** 키워드 명시, 해시태그는 정확한 5개 내외.

### 확정된 결정
| 항목 | 선택 |
|---|---|
| 니치 | **A(2030 마인드셋·돈 되는 생각) 메인 + B(문해력·어휘력) 서브 시리즈** |
| 자동화 범위 | 문구 → 이미지 생성 → **업로드까지 완전 자동** |
| 실행 위치 | **GitHub Actions** cron (PC 꺼져도 동작) |
| 이미지 호스팅 | **공개 GitHub 저장소의 `raw.githubusercontent.com` URL** (IG API가 이미지를 공개 URL로 가져가야 하므로) |
| 문구 공급 | **시드 30개(A 20 + B 10) 내가 작성 + 이후 JSON 수동 보충** |
| 발행 간격 | 기본 **2일에 1개**(`config/settings.yaml`에서 1~3일 조절) |

---

## 콘텐츠 전략

### 트랙 A — 2030 마인드셋 / 돈 되는 생각
- 형식: **캐러셀 4~6장**. 1장=후킹 제목, 2~5장=본문 한 줄씩, 마지막 장=한 줄 요약 + "저장해두고 다시 보기".
- 톤: 단정적·짧은 문장·2인칭("너"). 남의 명언 인용 금지, 본인 관점으로 재작성.
- 캡션: 1문장째에 타깃+주제 키워드("사회초년생 돈 관리 …"), 본문 2~3줄, CTA("공감되면 저장 / 필요한 친구 태그"), 해시태그 5개.
- 샘플 후킹: "돈이 안 모이는 진짜 이유" / "23살에 알았다면 좋았을 것 5" / "가난한 사람의 시간, 부자의 시간".

### 트랙 B — 문해력 / 어휘력 (서브, 주 1회 고정 시리즈)
- 형식: **캐러셀 3~5장**. 1장=헷갈리는 단어 쌍 제시, 2~3장=뜻 구분, 4장=예문, 5장=1초 암기 팁.
- 샘플: "지양 vs 지향" / "결재 vs 결제" / "안 vs 않" / "-든지 vs -던지" / "다르다 vs 틀리다".
- 팩트성이 있으므로 시드 문구는 국립국어원 기준으로 작성.

### 발행 리듬
- 큐에서 A·B를 **A,A,A,B 순환**(≈주 1회 B)으로 꺼냄. `settings.yaml`의 `rotation` 배열로 조정.
- 계정 정체성: 프로필명·바이오·고정 게시물·캡션 첫 줄이 같은 키워드를 말하도록 `README`에 가이드 포함.

---

## 프로젝트 구조

```
E:\개인\별\
├─ .github/workflows/publish.yml     # 매일 UTC 23:00 실행 → run_daily.py (스크립트가 발행일 여부 판단)
├─ config/
│  ├─ settings.yaml                  # 핸들, 간격, rotation, 색/폰트, IG user id(비밀 아님)
│  └─ secrets.example.env            # IG_ACCESS_TOKEN 등 템플릿 (실값은 Actions Secrets)
├─ content/
│  ├─ bank_A.json                    # A 시드 20개
│  ├─ bank_B.json                    # B 시드 10개
│  └─ SCHEMA.md                      # 항목 스키마 설명(수동 보충용)
├─ assets/fonts/                     # Pretendard (OFL 라이선스) .otf 번들 + LICENSE
├─ src/
│  ├─ render.py                      # content 항목 1개 → output/<date>_<slug>/1.png..N.png
│  ├─ publish.py                     # 이미지 공개 URL 목록 + 캡션 → IG Graph API 캐러셀 발행
│  ├─ queue.py                       # 다음 미발행 항목 선택(rotation), 상태 조회
│  ├─ run_daily.py                   # 오케스트레이터 (아래 흐름)
│  └─ notify.py                      # 큐 소진 시 GitHub 이슈 생성(선택)
├─ output/                           # 렌더된 PNG (커밋됨 → raw URL로 접근)
├─ state/log.json                    # 발행 이력, 마지막 발행일, 큐 포인터
├─ requirements.txt                  # pillow, pyyaml, requests
├─ SETUP.md                          # Phase 0: 계정/API 준비 체크리스트
└─ README.md                         # 운영 가이드(주간 루틴, 토큰 갱신, 문구 추가법)
```

---

## 핵심 파일 설계

### `src/render.py`
- 입력: content 항목 dict (`track`, `slug`, `slides:[{title/lines}]`, `caption`, `hashtags`, `alt`).
- Pillow로 **1080×1350(4:5)** PNG 생성:
  - 트랙별 배경/글자색 (A: 딥네이비 배경+화이트, B: 크림 배경+차콜 — `settings.yaml`).
  - 폰트: `assets/fonts/Pretendard-Bold/Regular.otf`. 자동 줄바꿈(문자폭 측정), 세로 중앙 정렬, 안전여백 96px.
  - 우하단 워터마크 `@핸들`, 우상단 페이지 인디케이터 `1/5`, 2장부터 하단에 "→".
- 출력 경로 반환. 순수 함수 위주로 작성해 로컬 미리보기(`python -m src.render --preview bank_A.json#0`) 가능.

### `src/publish.py`
- Instagram Graph API(그래프 버전 `v21.0` 고정) 캐러셀 3단계:
  1. 슬라이드마다 `POST /{IG_USER_ID}/media` (`image_url`, `is_carousel_item=true`) → child id
  2. `POST /{IG_USER_ID}/media` (`media_type=CAROUSEL`, `children=...`, `caption=...`) → container id
  3. `POST /{IG_USER_ID}/media_publish` (`creation_id=container id`)
- 토큰은 env `IG_ACCESS_TOKEN`(장기/시스템 유저 토큰). 429/일시오류 시 지수 백오프 3회.
- 단일 이미지 모드도 지원(`media_type` 생략).
- dry-run 플래그: 컨테이너까지만 만들고 publish 생략.

### `src/queue.py`
- `bank_A.json` + `bank_B.json` 로드, `state/log.json`의 published slug 집합 제외.
- `settings.yaml`의 `rotation`(예: `[A,A,A,B]`)과 이력 길이로 다음 트랙 결정 → 해당 뱅크에서 가장 오래된 미발행 항목 선택.
- 남은 미발행 개수 반환(소진 경고용).

### `src/run_daily.py` (Actions에서 실행)
1. `state/log.json`의 `last_published_at` + `settings.interval_days` 비교 → 오늘이 발행일 아니면 `exit 0`.
2. `queue.pick_next()` 로 항목 선택(없으면 경고 로그 + `exit 0`).
3. `render.py` 로 PNG 생성 → `output/<date>_<slug>/`.
4. `git add output state && git commit && git push` (Actions 기본 `GITHUB_TOKEN`). raw CDN 반영 대기 ~10초.
5. 각 PNG의 raw URL(`https://raw.githubusercontent.com/<user>/<repo>/main/output/...`) 구성 → `publish.publish_carousel(urls, caption)`.
6. 성공 시 `state/log.json`에 `{slug, permalink, published_at}` append → commit & push.
7. `queue` 잔여 < 5 이면 `notify.py`로 GitHub 이슈 1건 생성("문구 보충 필요").
- 모든 단계 로그를 stdout에 남겨 Actions 로그에서 추적.

### `.github/workflows/publish.yml`
- `on: schedule: - cron: "0 23 * * *"` (23:00 UTC = 08:00 KST) + `workflow_dispatch`(수동 실행).
- job: checkout(`fetch-depth:0`, `persist-credentials:true`) → setup-python 3.13 → `pip install -r requirements.txt` → `python -m src.run_daily`.
- env: `IG_ACCESS_TOKEN`, `IG_USER_ID` ← `secrets`. `GH_TOKEN: ${{ github.token }}`.
- 권한: `contents: write`, `issues: write`.

### `config/settings.yaml` (예시 키)
```yaml
handle: "@____"          # 확정 후 입력
interval_days: 2
rotation: [A, A, A, B]
graph_api_version: v21.0
tracks:
  A: { bg: "#0f1b3d", fg: "#ffffff", accent: "#7aa2ff" }
  B: { bg: "#f4ecdd", fg: "#2b2b2b", accent: "#c08a3e" }
size: [1080, 1350]
```

### `content/bank_A.json` 항목 스키마
```json
{
  "slug": "why-money-doesnt-stick",
  "track": "A",
  "slides": [
    {"title": "돈이 안 모이는 진짜 이유"},
    {"lines": ["수입이 부족해서가 아니다"]},
    {"lines": ["문제는 '기본 지출'이", "자동으로 세팅돼 있다는 것"]},
    {"lines": ["월급이 올라도", "기본값이 같이 올라간다"]},
    {"lines": ["먼저 기본값을 내려라.", "투자는 그다음이다."]},
    {"title": "저장해두고 이번 달에 점검하기"}
  ],
  "caption": "사회초년생이 돈 관리에서 가장 먼저 막히는 지점.\n수입이 아니라 '기본값'을 먼저 손봐야 한다.\n\n공감되면 저장 / 돈 모으고 싶은 친구 태그",
  "hashtags": ["#사회초년생", "#돈관리", "#재테크초보", "#2030재테크", "#소비습관"],
  "alt": "사회초년생 돈 관리: 기본 지출을 먼저 줄여야 저축이 된다는 설명 카드"
}
```

---

## Phase 0 — 사용자가 직접 준비 (SETUP.md 로 문서화)

계정/자격증명 관련이라 내가 대신 못 하는 부분. 순서:
1. 인스타그램을 **프로페셔널(크리에이터/비즈니스)** 계정으로 전환.
2. **Facebook 페이지** 생성 후 인스타그램 계정과 연결.
3. [developers.facebook.com](https://developers.facebook.com) 에서 앱 생성 → 제품에 **Instagram Graph API** 추가.
4. 권한: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
5. **장기 토큰** 발급 → 가급적 Business Manager의 **시스템 유저 토큰(무기한)** 사용 권장.
6. `IG_USER_ID`(인스타 비즈니스 계정 ID) 확인.
7. GitHub 계정 생성 → **공개 저장소** 만들고 이 프로젝트 push.
8. 저장소 **Settings → Secrets and variables → Actions** 에 `IG_ACCESS_TOKEN`, `IG_USER_ID` 등록.
9. 핸들 확정 후 `config/settings.yaml`의 `handle` 입력.

> 공개 저장소를 쓰는 이유: IG API가 이미지를 공개 URL로 내려받아야 함. 게시물 자체가 어차피
> 공개되므로 이미지/문구 저장소 공개는 문제 없음. **비밀값은 저장소가 아니라 Actions Secrets에만** 둠.
> (저장소를 비공개로 유지하려면 대안: Action 안에서 catbox.moe/tmpfiles.org 임시 업로드 → 그 URL로 발행. 신뢰성은 공개 raw가 더 높음.)

---

## 구현 순서

1. `requirements.txt`, 폴더 골격, `config/settings.yaml`, `config/secrets.example.env`.
2. `assets/fonts/` 에 Pretendard(OFL) 내려받아 번들 + LICENSE 파일.
3. `content/bank_A.json`(20) + `content/bank_B.json`(10) 시드 작성 + `SCHEMA.md`.
4. `src/render.py` + 로컬 미리보기 → PNG 30세트 눈으로 확인.
5. `src/queue.py`, `src/run_daily.py`(발행일 판정·git·오케스트레이션), `state/log.json` 초기값.
6. `src/publish.py` + `--dry-run`.
7. `.github/workflows/publish.yml` + `src/notify.py`.
8. `SETUP.md`, `README.md` 작성.

---

## 검증

- **렌더 단독**: `python -m src.render --preview "content/bank_A.json#0"` → `output/preview/` PNG 열어 폰트/줄바꿈/색 확인. 30개 전부 배치 렌더해 훑기.
- **큐 로직**: `python -m src.queue --status` → 다음 항목·잔여 개수·rotation 결과 출력. `log.json`에 더미 이력 넣고 트랙 순환 확인.
- **발행 dry-run**: 로컬 `.env`에 실토큰 넣고 `python -m src.publish --dry-run --item "content/bank_B.json#0"` → 컨테이너 생성까지 성공(응답 id) 확인, publish 미실행.
- **엔드투엔드(수동 1회)**: GitHub에 push 후 Actions에서 `workflow_dispatch` 수동 실행 → 실제 1건 발행되는지 확인. 성공 시 `state/log.json` 갱신 커밋 확인, 인스타 앱에서 캐러셀·캡션·대체텍스트 확인.
- 이후 cron이 `interval_days`에 맞춰 자동 발행. Actions 로그로 "오늘은 발행일 아님/발행 완료" 추적.

---

## 운영 (README.md 에 정리)

- **주간 루틴(10분)**: `bank_A.json`/`bank_B.json`에 항목 몇 개 추가 push. 큐 <5 이면 자동 이슈 알림.
- **토큰 갱신**: 시스템 유저 토큰이면 불필요. 장기 사용자 토큰이면 ~55일마다 갱신(스크립트 `src/refresh_token.py` 제공, 수동 실행 또는 월 1회 워크플로).
- **간격 변경**: `settings.yaml`의 `interval_days` 1~3 조정.
- **중단**: 워크플로 disable.

---

## 제약 / 리스크

- IG Graph API는 **비즈니스/크리에이터 계정 + FB 페이지 연결 필수**. 개인 계정은 발행 API 불가.
- 발행 한도 25건/24h — 현 계획(2일 1건)엔 여유.
- 이미지 URL은 공개 접근 가능해야 함 → 공개 저장소 사용(비밀값은 분리).
- 자동 발행은 계정 성장의 필요조건일 뿐 충분조건 아님. 초반엔 수동 실행으로 문구 반응 보며 톤 조정 권장(→ README에 명시).
- 폰트는 OFL 라이선스 Pretendard만 번들(상업적 사용·재배포 허용).
