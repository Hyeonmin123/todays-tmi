# 오늘의 잡다한 정보 (@today.tminformation)

'노트/필기' 스타일 **2장 캐러셀**(1장=제목만 크게, 2장=내용) + 상세 캡션을 자동으로 올리는 파이프라인.
같은 내용을 **릴스(세로 영상)로도** 발행. GitHub Actions가 하루 여러 번 점검해서
목표 개수까지 렌더 → 발행 → 이력 기록한다.

- 최초 준비(계정/토큰/저장소): **[SETUP.md](SETUP.md)**
- 설계 배경(초기 버전): **[docs/PLAN.md](docs/PLAN.md)** — 주제는 이후 'TMI/신기한 사실'로 변경됨

---

## 콘텐츠

| 트랙 | 주제 | 파일 |
|---|---|---|
| **A** | 오늘의 TMI — 신기한 사실·잡학 (역사·동물·우주·과학·상식 교정). 각 카드에 출처 표기. | `content/bank_A.json` |

- 단일 트랙 (`config/settings.yaml` 의 `rotation: [A]`).
- 보류된 트랙: `content/bank_kkultip.parked.json`(생활 꿀팁 34개), `content/bank_B.parked.json`(문해력). 둘 다 비활성.
- 되살리려면 스키마 확인 후 `bank_B.json` 등으로 이름 바꾸고 `rotation` 에 추가.

---

## 구조

```
config/settings.yaml      발행 간격·핸들·색·rotation
content/bank_A.json        오늘의 TMI / 신기한 사실 (지금 15개) — 유일한 활성 트랙
content/bank_kkultip.parked.json  생활 꿀팁 34개 (보류, 비활성)
content/bank_B.parked.json 문해력 트랙 (보류, 비활성)
content/SCHEMA.md          항목 작성법
src/render.py              항목 1개 -> 2장 캐러셀 (커버 + 내용)
src/reel.py                2장을 세로 영상(mp4)으로 -> 릴스용
src/queue.py               다음 발행 항목 선택
src/publish.py             Instagram API 캐러셀/릴스 발행
src/run_daily.py           오케스트레이터 (Actions가 실행)
src/notify.py              큐 소진 시 GitHub 이슈 알림
src/refresh_token.py       토큰 갱신(60일마다)
.github/workflows/publish.yml   KST 08:00 / 14:00 / 20:00 실행
state/log.json             발행 이력 (자동 갱신)
output/<날짜>_<slug>/      발행된 카드·영상 (자동 커밋)
```

---

## 자주 하는 일

### 콘텐츠 추가 (주 10분)
새 TMI 항목을 `content/bank_A.json` **아래쪽에** 붙이고 commit & push.
형식은 `content/SCHEMA.md`. 사실은 반드시 출처 확인 후 `source` 필드에 표기.
추가 전에 미리보기로 확인:
```bash
python -m src.render --preview "content/bank_A.json#-1"   # 마지막 항목
```
> 남은 문구가 5개 미만이 되면 GitHub에 자동으로 "보충 필요" 이슈가 열린다.

### 상태 확인
```bash
python -m src.queue --status
```
다음에 뭐가 나갈지, 남은 개수, 마지막 발행일을 보여준다.

### 발행 간격 바꾸기
`config/settings.yaml` 의 `interval_days` 를 1~3으로. push 하면 다음 실행부터 적용.

### 지금 당장 1건 발행 / 렌더만 확인
저장소 **Actions → 자동 발행 → Run workflow**:
- `dry_run` 체크 = 렌더·URL만 확인 (발행 안 함)
- `force` 체크 = 발행일 무시하고 즉시 1건 발행

### 잠시 멈추기 / 재개
저장소 **Actions → 자동 발행 → 우측 ··· → Disable workflow** / 다시 Enable.

### 토큰 갱신 (장기 사용자 토큰을 쓰는 경우만, ~55일마다)
```bash
python -m src.refresh_token
```
출력된 새 토큰을 저장소 Secret `IG_ACCESS_TOKEN` 에 교체.
시스템 사용자 토큰(만료 없음)을 쓰면 이 단계 자체가 없음.

---

## 로컬에서 테스트

```bash
pip install -r requirements.txt

# 1) 카드 전체 미리보기 -> output/preview/
python -m src.render --preview-all

# 2) 발행 직전까지 시뮬레이션 (git/발행 없음)
python -m src.run_daily --dry-run

# 3) 실제 발행만 로컬에서 (git 커밋 없이, 이미지 URL은 이미 push된 것이어야 함)
#    config/secrets.env 에 IG_USER_ID, IG_ACCESS_TOKEN 채운 뒤:
python -m src.run_daily --no-git --force
```

`config/secrets.env` 는 `config/secrets.example.env` 를 복사해서 만든다(gitignore됨).

---

## 운영 팁

- **처음 2~3주는 수동(Run workflow)으로** 돌리며 어떤 문구가 저장/공유가 잘 되는지 보고,
  잘 되는 톤 쪽으로 `bank_*.json` 을 채워라. 자동화는 그다음에 켜도 된다.
- 프로필 이름·소개글·고정 게시물·캡션 첫 문장에 **같은 키워드**(예: "TMI", "잡학", "신기한 사실")를
  넣어 계정 주제를 일관되게. 2026 인스타 검색·추천이 이걸 본다.
- 캡션 첫 문장은 항상 "**누구의 어떤 고민**"으로 시작. 해시태그는 정확한 5개.
- 이미지는 저장소에 남아 계정 백업이 된다. 지우지 말 것.

---

## 한계 / 주의

- 인스타 발행 API는 **프로페셔널 계정 + 페이스북 페이지 연결** 필수.
- 이미지 URL은 공개 접근 가능해야 함 → 저장소는 Public. **토큰은 저장소가 아니라 Actions Secrets** 에만.
- Graph API 발행 한도 25건/24시간 (현재 계획엔 여유).
- 자동 발행은 꾸준함을 보장할 뿐, 팔로워 성장은 문구의 질에 달렸다.
- **릴스는 무음으로 올라감.** 올라온 뒤 인스타 앱에서 릴스 열어 트렌딩 오디오를 붙이면
  도달에 유리. 또는 `assets/audio/loop.mp3` 를 두고 `config` 의 `reel_audio` 에 경로를 넣으면
  그 음악이 깔림(저작권 프리만).
- 폰트: DoHyeon(제목)·Gaegu(본문)·Pretendard(예비) — 모두 SIL Open Font License.
- ffmpeg 는 `imageio-ffmpeg` 가 번들 (시스템 설치 불필요).
