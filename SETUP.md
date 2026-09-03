# SETUP — 최초 1회 준비

이 문서의 단계는 **직접** 해야 합니다(계정 생성·로그인·토큰 발급은 자동화 불가).
다 끝내면 이후에는 손 안 대도 자동 발행됩니다.

소요: 처음이면 40~60분.

---

## 1. 인스타그램 계정 준비

1. 발행에 쓸 인스타그램 계정을 **프로페셔널 계정**으로 전환
   (프로필 → ☰ → 설정 및 활동 → 크리에이터 도구 및 관리 → **프로페셔널 계정으로 전환** → 크리에이터).
2. 페이스북 **페이지**를 하나 만들고 인스타 계정과 연결
   (Instagram 로그인 방식엔 필수는 아니지만 만들어두면 무방).

> 개인(일반) 계정은 발행 API를 못 씁니다. 프로페셔널 필수.

---

## 2. Meta 앱 만들고 토큰 받기 (Instagram 로그인 방식)

1. <https://developers.facebook.com> 로그인 → **앱** → **앱 만들기**
   - 앱 상세 정보: 이름(예: `todays-tmi`), 이메일 → 다음
   - **이용 사례**: 왼쪽 필터 "콘텐츠 관리" → **"Instagram에서 메시지 및 콘텐츠 관리"** 선택 → 다음
   - 비즈니스: "아직 연결하고 싶지 않음" → 다음 → 앱 생성
2. 대시보드 → **"Instagram에서 메시지 및 콘텐츠 관리 맞춤 설정 이용 사례"** 클릭
   → 왼쪽 **"권한 및 기능"**:
   - `instagram_business_basic` — "테스트 준비 완료" 확인
   - `instagram_business_content_publish` — **추가** (게시 권한, 목록에 없으면 검색해서 추가)
3. **앱 역할 → 역할 → "Instagram 테스터"** 탭 → **사람 추가** → 발행용 인스타 아이디 입력
   → 인스타 웹/앱 **설정 → 앱 및 웹사이트 → "테스터 초대" → 수락**
4. 다시 이용 사례 설정 화면 → **"2. 액세스 토큰 생성"** → **계정 추가**
   → 그 인스타 계정으로 로그인·허용 → **액세스 토큰 생성** 클릭
5. 팝업에 뜨는 값:
   - 계정 아래 숫자 ID (17841… ) → **`IG_USER_ID`**
   - `IGAA…` 로 시작하는 토큰 (60일 유효) → **`IG_ACCESS_TOKEN`**
   - 토큰은 한 번만 표시되니 바로 복사해 안전한 곳에 저장.

> 토큰은 60일마다 갱신 필요. `python -m src.refresh_token` 실행 → 새 토큰을
> GitHub Secret 에 교체. (앱 ID/시크릿 없이 현재 토큰만으로 갱신됨)

---

## 3. GitHub 저장소

1. <https://github.com> 계정 생성/로그인 → **New repository** → **Public** 로 생성
   (이미지가 공개 URL로 접근돼야 인스타가 받아감. 토큰은 코드에 안 들어가니 안전).
2. 이 폴더(`E:\개인\별`)를 그 저장소로 올린다:
   ```bash
   cd "E:\개인\별"
   git init
   git add .
   git commit -m "init: 별 자동 발행 파이프라인"
   git branch -M main
   git remote add origin https://github.com/<너의아이디>/<저장소>.git
   git push -u origin main
   ```
3. 저장소 → **Settings → Secrets and variables → Actions → New repository secret**:
   | 이름 | 값 |
   |---|---|
   | `IG_USER_ID` | 2번에서 얻은 숫자 ID |
   | `IG_ACCESS_TOKEN` | 2번에서 얻은 장기/시스템 토큰 |
4. 저장소 → **Settings → Actions → General → Workflow permissions** →
   **Read and write permissions** 켜기 (봇이 이미지·이력을 커밋해야 함).

---

## 4. 설정값 입력

`config/settings.yaml` 에서:
- `handle`: 본인 인스타 핸들(`@` 포함). 이미지 워터마크에 찍힘.
- `interval_days`: 1(매일) ~ 3(3일에 1개). 기본 2.
- 색/폰트는 그대로 둬도 됨.

바꾼 뒤 commit & push.

---

## 5. 첫 발행 테스트

1. 저장소 → **Actions** 탭 → **자동 발행** 워크플로 → **Run workflow**
   - `dry_run` 체크 → 실행 → 로그에서 렌더/URL 확인(실제 발행 안 함).
2. 이상 없으면 다시 **Run workflow** → `force` 체크 → 실행 → **실제 1건 발행**.
3. 인스타 앱에서 게시물 확인. `state/log.json` 에 이력이 커밋됐는지도 확인.

이후로는 매일 08:00(KST) 자동 점검 → `interval_days` 마다 1건씩 발행됩니다.

---

## 다음

운영(문구 추가, 토큰 갱신, 발행 멈추기)은 [README.md](README.md) 참고.
