# 문구 뱅크 스키마

`content/bank_A.json`(오늘의 TMI / 신기한 사실)이 **항목의 배열**이자 유일한 활성 트랙이다.
큐는 위에서부터 소비하고, 이미 올린 항목(`state/log.json` 의 slug)은 건너뛴다.
새 항목은 파일 **아래쪽에** 추가. 사실은 출처 확인 후 `source` 필드에 표기한다.

한 항목 = **잘 꾸민 카드 한 장**(1080×1350). 본문 항목이 6개를 넘으면 자동으로 2장이 된다.

## 항목 형식

```jsonc
{
  "slug": "microwave-grease",        // 고유 ID. 영문-소문자-하이픈. 재사용 금지(이력 키).
  "track": "A",
  "kicker": "오늘의 TMI",             // 좌상단 칩 문구 (생략 시 설정의 트랙 이름)
  "title": "전자레인지 기름때,\n물 한 컵이면 끝",   // \n 으로 줄바꿈 직접 지정
  "title_highlight": "물 한 컵",       // (선택) 제목 중 이 부분에 밑줄 강조. 짧게(2~6자).
  "body": {
    "type": "steps",                  // "steps"(번호) | "bullets"(점) | "text"(문단)
    "items": [                        // 3~5개 권장. 한 줄은 26자 안팎이면 안 접힘.
      "내열 그릇에 물을 반쯤 붓고 레몬이나 식초 한 스푼",
      "3분 돌려 김이 꽉 차게 한 뒤 문 열지 말고 2분 뜸",
      "마른행주로 쓱 닦으면 눌어붙은 것도 떨어진다"
    ]
    // type이 "text"면 items 대신:  "text": "문단 내용..."
  },
  "outro": "주 1회 해두면 냄새도 안 남는다",   // (선택) 하단 저장유도 박스. 없으면 박스 생략.
  "source": "출처: 정부24",            // (선택) 좌하단 작은 출처
  "caption": "첫 문장에 '누구의 어떤 상황' 키워드.\n방법 요약.\n\n저장 필수 · 필요한 친구 태그",
  "hashtags": ["#TMI", "#오늘의TMI", "#잡학", "#신기한사실", "#주제"],  // 항상 붙는 5개
  "extra_hashtags": ["#세계사", "#고대이집트", "#역사스타그램", "#피라미드", "#역사이야기"],
  //  ↑ 그날 주제와 연관된 5개. 발행 이력이 settings 의 extra_hashtags_until_post 미만인
  //    동안에만 붙음(초반 유입용). hashtags 와 겹치지 않게.
  "alt": "이미지 대체텍스트. 한 문장으로 무엇을 설명하는 카드인지."
}
```

## 규칙
- 제목은 2줄 이내, 한 줄에 하나의 핵심.
- `items` 한 줄은 26자 안팎. 길면 자동 줄바꿈되지만 미리보기로 확인.
- 캡션 첫 문장에 검색 키워드(상황 + 대상). 해시태그 5개, 주제와 정확히 맞는 것만.
- 사실 확인 필수. 화학용품 주의사항(예: 과탄산은 울·실크 금지)이 있으면 items나 outro에 한 줄.
- 남의 게시물을 그대로 옮기지 말 것. 본인 표현으로.

## 미리보기
```bash
python -m src.render --preview "content/bank_A.json#0"    # 0번째 항목
python -m src.render --preview "content/bank_A.json#-1"    # 마지막 항목
python -m src.render --preview-all                         # 전체 -> output/preview/
```

> `content/bank_B.parked.json` 은 예전에 보류한 '문해력' 트랙(옛 스키마). 지금은 안 쓴다.
> 되살리려면 이 스키마에 맞게 고쳐 별도 트랙(C 등)으로 붙이고 `rotation` 에 넣으면 된다.

## 예비 폴더 (`content/reserve/pool.json`)

썩 끌리지 않아서 활성 뱅크(`bank_A.json`)에서 뺀 항목을 저장해두는 곳. 스키마는 동일.

- 큐는 평소엔 `bank_A.json` 만 소비한다.
- `bank_A.json` 이 전부 소진됐는데 **그 시점까지 새 항목을 추가하라고 지시받지 않았으면**,
  자동으로 `reserve/pool.json` 에서 꺼내 쓴다 (`src/queue.py` 의 `pick_next`).
- 항목을 예비로 보낼 때는 `bank_A.json` 에서 잘라 `reserve/pool.json` 배열에 붙이면 된다.
