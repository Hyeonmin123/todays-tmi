"""릴스와 같은 소재로 만드는 사진 게시물(캐러셀, 1080x1350).

  1장 커버: 릴스 썸네일과 같은 사진 + 훅 문장(훅에 인물 이름이 들어 있다)
  2~N장: 사진을 어둡게 깔고 반투명 패널 위에 상세 설명(영상에 못 담은 내용)
  마지막 장: 결론 + 출처 + 공유 유도
디자인 규칙은 CLAUDE.md 와 릴스(reel_stock)와 동일(블루, 도현체, 배지 글자만, 존댓말).

사용: python -m src.post_stock <slug>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from .common import OUTPUT_DIR, ROOT
from .reel_stock import HL, TITLE_FONT, _draw_text, _search
from .render import _font, _rgb, _wrap

W, H = 1080, 1350
BODY_FONT = "Pretendard-SemiBold.otf"


def _bg(img: Image.Image, brightness: float) -> Image.Image:
    sc = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * sc) + 1, int(img.height * sc) + 1), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return ImageEnhance.Brightness(img.crop((x, y, x + W, y + H))).enhance(brightness).convert("RGBA")


def _gradient(top: int, bottom_from: int) -> Image.Image:
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    for y in range(H):
        a = 0
        if y < top:
            a = int(150 * (1 - y / top))
        elif y > bottom_from:
            a = int(190 * min(1.0, (y - bottom_from) / (H - bottom_from)))
        if a:
            d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    return g


def _chrome(im: Image.Image, page: int, total: int, arrow: bool = False):
    d = ImageDraw.Draw(im)
    d.text((60, 56), "오늘의 TMI", font=_font(TITLE_FONT, 44), fill=(255, 255, 255, 255),
           stroke_width=5, stroke_fill=(0, 0, 0, 200))
    pf = _font(TITLE_FONT, 40)
    t = f"{page} / {total}"
    d.text((W - 60 - d.textlength(t, font=pf), 58), t, font=pf, fill=(255, 255, 255, 235),
           stroke_width=5, stroke_fill=(0, 0, 0, 200))
    if arrow:
        af = _font(TITLE_FONT, 64)
        d.text((W - 60 - d.textlength("→", font=af), H - 130), "→", font=af, fill=(255, 255, 255, 240),
               stroke_width=6, stroke_fill=(0, 0, 0, 200))


def _cover(item: dict, used: set, total: int) -> Image.Image:
    im = _bg(_search(item["hook_query"], used, item.get("hook_img")), 0.62)
    im.alpha_composite(_gradient(420, 700))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _draw_text(layer, item["hook"], 116, 760, 1.0, 0)
    im.alpha_composite(layer)
    _chrome(im, 1, total, arrow=True)
    return im


def _card(item: dict, c: dict, page: int, total: int, used: set, last: bool) -> Image.Image:
    im = _bg(_search(item["hook_query"], used, c.get("img")), 0.55)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pad, mx = 56, 84
    tf, bf = _font(TITLE_FONT, 68), _font(BODY_FONT, 45)
    lines = _wrap(d, c["body"], bf, W - 2 * mx - 2 * pad)
    lh = int(45 * 1.55)
    extra = []
    if last:
        extra = [item.get("source", ""), "저장해 두고 친구에게 공유하기"]
    ph = pad * 2 + 68 + 34 + lh * len(lines) + (44 + 40 * len(extra) if extra else 0)
    y0 = (H - ph) // 2
    d.rounded_rectangle([mx, y0, W - mx, y0 + ph], radius=36, fill=(0, 0, 0, 150))
    d.rounded_rectangle([mx + pad, y0 + pad + 74, mx + pad + 96, y0 + pad + 80], radius=3, fill=(*_rgb(HL), 255))
    d.text((mx + pad, y0 + pad - 6), c["title"], font=tf, fill=(*_rgb(HL), 255))
    y = y0 + pad + 74 + 34
    for ln in lines:
        d.text((mx + pad, y), ln, font=bf, fill=(255, 255, 255, 255))
        y += lh
    if extra:
        y += 30
        sf, cf = _font(BODY_FONT, 32), _font(TITLE_FONT, 44)
        d.text((mx + pad, y), extra[0], font=sf, fill=(255, 255, 255, 170))
        d.text((mx + pad, y + 46), extra[1], font=cf, fill=(*_rgb(HL), 255))
    im.alpha_composite(layer)
    _chrome(im, page, total)
    return im


def render_post(item: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = [dict(c) for c in item["post_cards"]]
    defaults = [item["beats"][0].get("img"), item.get("reveal_img")]
    for c, d in zip(cards, defaults):
        c.setdefault("img", d)
    total = len(cards) + 1
    used: set[int] = set()
    slides = [_cover(item, used, total)]
    for i, c in enumerate(cards):
        slides.append(_card(item, c, i + 2, total, used, last=(i == len(cards) - 1)))
    paths = []
    for n, s in enumerate(slides, 1):
        p = out_dir / f"{n}.jpg"
        s.convert("RGB").save(p, quality=92)
        paths.append(p)
    return paths


if __name__ == "__main__":
    slug = sys.argv[1]
    items = json.loads((ROOT / "content" / "bank_people.json").read_text(encoding="utf-8"))
    it = next(x for x in items if x["slug"] == slug)
    for p in render_post(it, OUTPUT_DIR / "preview" / ("_post_" + slug)):
        print("ok ->", p)
