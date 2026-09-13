"""문구 항목 1개를 2장 캐러셀로 렌더링한다.

  1장(커버): 제목만 크게 — 굵은 고딕 + 줄마다 형광펜. 스크롤을 멈추는 후킹용.
  2장(내용): 제목 축약 + 번호 없는 점 불릿 + 한 줄 정리 + 출처.
  상세 설명은 인스타 캡션에.

노트/필기 톤: 따뜻한 종이색 + 점 그리드 배경, 본문은 손글씨체(Gaegu).

사용:
  python -m src.render --preview "content/bank_A.json#0"
  python -m src.render --preview-all
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import FONT_DIR, OUTPUT_DIR, load_all_items, load_settings


# ---------- 유틸 ----------
def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def _blend(fg: str, bg: str, a: float) -> tuple[int, int, int]:
    f, b = _rgb(fg), _rgb(bg)
    return tuple(round(f[i] * a + b[i] * (1 - a)) for i in range(3))  # type: ignore


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _tokens(para: str, protect: str | None) -> list[str]:
    """공백 기준 분리하되, protect 문구(내부에 공백 있을 수 있음)는 한 토큰으로 묶는다."""
    if not protect or protect not in para:
        return para.split(" ")
    i = para.index(protect)
    before, after = para[:i].rstrip(" "), para[i + len(protect):].lstrip(" ")
    toks = (before.split(" ") if before else []) + [protect] + (after.split(" ") if after else [])
    return toks


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_w: float, protect: str | None = None) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if d.textlength(para, font=font) <= max_w:
            out.append(para)
            continue
        cur = ""
        for w in _tokens(para, protect):
            t = (cur + " " + w).strip()
            if d.textlength(t, font=font) <= max_w:
                cur = t
            else:
                if cur:
                    out.append(cur)
                cur = w
        out.append(cur)
    return out


_HL_RE = re.compile(r"\*\*(.+?)\*\*")


def _split_highlight(text: str) -> tuple[str, str | None]:
    """본문 불릿의 '**강조**' 표시를 뽑아 (평문, 강조구) 로 분리."""
    m = _HL_RE.search(text)
    if not m:
        return text, None
    return text[:m.start()] + m.group(1) + text[m.end():], m.group(1)


def _safe_title(text: str) -> str:
    """제목용 고딕 폰트(DoHyeon)에 없는 글자 치환."""
    return text.replace("·", ",").replace("・", ",").replace("–", "-").replace("—", "-")


def _fit(d, text, fname, max_w, max_h, sizes, ratio=1.16):
    """명시한 줄바꿈이 유지되면서 max_w x max_h 에 드는 가장 큰 크기."""
    text = _safe_title(text)
    exp = text.split("\n")
    best = None
    for s in sizes:
        f = _font(fname, s)
        lines = _wrap(d, text, f, max_w)
        asc, desc = f.getmetrics()
        lh = int((asc + desc) * ratio)
        if len(lines) == len(exp) and lh * len(lines) <= max_h:
            best = (f, lines, lh)
    if best:
        return best
    f = _font(fname, sizes[0])
    lines = _wrap(d, text, f, max_w)
    asc, desc = f.getmetrics()
    return (f, lines, int((asc + desc) * ratio))


def _dot_grid(d: ImageDraw.ImageDraw, w: int, h: int, color, step: int = 46):
    for gx in range(step // 2, w, step):
        for gy in range(step // 2, h, step):
            d.ellipse([gx - 1.4, gy - 1.4, gx + 1.4, gy + 1.4], fill=color)


def _wavy(d, x0, x1, y, color, amp=2.6, width=5, period=32):
    pts = []
    x = x0
    while x <= x1:
        pts.append((x, y + math.sin((x - x0) / period * math.pi) * amp))
        x += 6
    if len(pts) >= 2:
        d.line(pts, fill=color, width=width, joint="curve")


def _dot(d, cx, cy, r, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def _marker(width: int, height: int, color) -> Image.Image:
    r, g, b = _rgb(color) if isinstance(color, str) else color
    pad = 8
    im = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([pad, pad, pad + width, pad + height],
                                         radius=height // 2, fill=(r, g, b, 150))
    return im.rotate(-1.2, expand=True, resample=Image.BICUBIC)


def _kicker_badge(d, x, y, text, font, fg, bg):
    """카드 좌상단 '오늘의 TMI' 태그를 얇은 테두리 알약 배지로."""
    tw = d.textlength(text, font=font)
    pad_x, h = 18, 44
    d.rounded_rectangle([x, y, x + tw + pad_x * 2, y + h], radius=h // 2,
                         outline=_blend(fg, bg, 0.55), width=2)
    d.text((x + pad_x, y + (h - font.size) / 2 - 4), text, font=font, fill=fg)
    return x + tw + pad_x * 2, h


def _tag_row(d, cx_center, y, max_w, tags, font, fg, bg) -> float:
    """관련 태그를 가운데 정렬 알약으로. 다음 줄까지 자동 배치. 마지막 y 반환."""
    if not tags:
        return y
    pad_x, gap, h = 20, 14, 50
    rows: list[list[tuple[str, float]]] = []
    cur, cur_w = [], 0.0
    for t in tags:
        w = d.textlength(t, font=font) + pad_x * 2
        add = w if not cur else gap + w
        if cur and cur_w + add > max_w:
            rows.append(cur)
            cur, cur_w = [], 0.0
            add = w
        cur.append((t, w))
        cur_w += add
    if cur:
        rows.append(cur)
    for row in rows:
        row_w = sum(w for _, w in row) + gap * (len(row) - 1)
        cx = cx_center - row_w / 2
        for t, w in row:
            d.rounded_rectangle([cx, y, cx + w, y + h], radius=h // 2,
                                 outline=_blend(fg, bg, 0.4), width=2)
            d.text((cx + pad_x, y + (h - font.size) / 2 - 4), t, font=font, fill=_blend(fg, bg, 0.85))
            cx += w + gap
        y += h + 16
    return y


def _bg(cfg, theme):
    W, H = cfg["size"]
    img = Image.new("RGB", (W, H), theme["bg"])
    d = ImageDraw.Draw(img)
    _dot_grid(d, W, H, _blend(theme.get("sub", "#8A7A5C"), theme["bg"], 0.16))
    return img, d


def _footer(d, cfg, theme, item, part, parts):
    W, H = cfg["size"]
    m = cfg.get("margin", 90)
    sub = theme.get("sub", "#8A7A5C")
    hf = _font(cfg["fonts"]["regular"], 24)
    fy = H - m - 2
    src = item.get("source")
    if src and part == parts:
        while src and d.textlength(src, font=hf) > (W - 2 * m) * 0.58:
            src = src[:-1]
        d.text((m, fy), src, font=hf, fill=sub)
    handle = cfg.get("handle", "@your_handle")
    d.text((W - m - d.textlength(handle, font=hf), fy), handle, font=hf, fill=sub)


# ---------- 1장: 커버 ----------
def _cover(item: dict, cfg: dict) -> Image.Image:
    W, H = cfg["size"]
    m = cfg.get("margin", 90)
    th = cfg["tracks"][item["track"]]
    bg, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#8A7A5C")
    Ft = cfg["fonts"].get("title", cfg["fonts"]["bold"])
    img, d = _bg(cfg, th)
    x, max_w = m, W - 2 * m

    _kicker_badge(d, m, m - 6, item.get("kicker") or th.get("name", ""),
                  _font(cfg["fonts"]["bold"], 30), sub, bg)
    ind = "1 / 2"
    inf = _font(cfg["fonts"]["regular"], 26)
    d.text((W - m - d.textlength(ind, font=inf), m + 2), ind, font=inf, fill=sub)

    tf, lines, tlh = _fit(d, item["title"], Ft, max_w, 640,
                          range(64, 132, 2), ratio=1.22)
    block_h = tlh * len(lines)
    y = (H - block_h) / 2 - 20
    asc = tf.getmetrics()[0]
    for ln in lines:
        lw = d.textlength(ln, font=tf)
        mk = _marker(int(lw + 26), int(asc * 0.60), accent)
        img.paste(mk, (int(x - 12), int(y + asc * 0.24)), mk)
        d.text((x, y), ln, font=tf, fill=fg)
        y += tlh

    # 제목 아래 빈 공간을 관련 태그로 채움(예비 유입 키워드 미리 보여주기)
    tags = [t.lstrip("#") for t in item.get("extra_hashtags", [])[:3]]
    _tag_row(d, W / 2, y + 64, max_w, tags, _font(cfg["fonts"]["regular"], 30), fg, bg)

    hint = "→  넘겨서 보기"
    hf = _font(cfg["fonts"]["bold"], 32)
    d.text(((W - d.textlength(hint, font=hf)) / 2, H - m - 78), hint, font=hf, fill=sub)
    _footer(d, cfg, th, item, 1, 2)
    return img


# ---------- 2장~: 내용 ----------
def _content(item: dict, cfg: dict, units: list[str], part: int, parts: int) -> Image.Image:
    W, H = cfg["size"]
    m = cfg.get("margin", 90)
    th = cfg["tracks"][item["track"]]
    bg, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#8A7A5C")
    Ft = cfg["fonts"].get("title", cfg["fonts"]["bold"])
    Fb, Fr = cfg["fonts"]["bold"], cfg["fonts"]["regular"]
    img, d = _bg(cfg, th)
    x, max_w = m, W - 2 * m

    d.text((m, m), item.get("kicker") or th.get("name", ""),
           font=_font(Fb, 30), fill=sub)
    ind = f"{part + 1} / {parts + 1}"
    inf = _font(Fr, 26)
    d.text((W - m - d.textlength(ind, font=inf), m + 2), ind, font=inf, fill=sub)
    y = m + 30 + 34

    tf, tlines, tlh = _fit(d, item["title"], Ft, max_w, 220, range(38, 62, 2), ratio=1.14)
    for ln in tlines:
        d.text((x, y), ln, font=tf, fill=fg)
        y += tlh
    y += 12
    _wavy(d, x, x + min(max_w * 0.44, 280), y, sub, amp=2.4, width=4)
    y += 40

    footer_h = 44
    bottom = H - m - footer_h
    outro = item.get("outro") if part == parts else None

    split = [_split_highlight(u) for u in units]
    clean_units = [c for c, _ in split]
    hl_list = [h for _, h in split]

    chosen = None
    total = 0.0
    for bs in range(52, 27, -2):
        bf = _font(Fr, bs)
        a1, d1 = bf.getmetrics()
        lh = int((a1 + d1) * 1.34)
        wrapped = [_wrap(d, u, bf, max_w - 46, protect=h) for u, h in zip(clean_units, hl_list)]
        body_core = sum(lh * len(w) for w in wrapped)
        of = _font(Fb, max(bs - 3, 26))
        a2, d2 = of.getmetrics()
        olh = int((a2 + d2) * 1.3)
        owrap = _wrap(d, outro, of, max_w) if outro else []
        outro_core = olh * len(owrap)
        n_gaps = len(units) + (1 if outro else 0)
        total = body_core + outro_core
        if total + 18 * n_gaps <= bottom - y or bs == 30:
            chosen = (bf, lh, wrapped, of, olh, owrap, n_gaps)
            break

    bf, lh, wrapped, of, olh, owrap, n_gaps = chosen
    bfb = _font(Fb, bf.size)
    basc = bfb.getmetrics()[0]
    slack = (bottom - y) - total
    gap = max(20, min(slack / max(n_gaps, 1), 96))
    for idx, w in enumerate(wrapped):
        hl = hl_list[idx]
        cy = y + bf.getmetrics()[0] * 0.52
        _dot(d, x + 8, cy, 7, sub)
        for ln in w:
            px = x + 46
            if hl and hl in ln:
                pre, suf = ln.split(hl, 1)
                if pre:
                    d.text((px, y), pre, font=bf, fill=_blend(fg, bg, 0.92))
                    px += d.textlength(pre, font=bf)
                hl_w = d.textlength(hl, font=bfb)
                mk = _marker(int(hl_w + 14), int(basc * 0.56), accent)
                img.paste(mk, (int(px - 6), int(y + basc * 0.22)), mk)
                d.text((px, y), hl, font=bfb, fill=fg)
                px += hl_w
                if suf:
                    d.text((px, y), suf, font=bf, fill=_blend(fg, bg, 0.92))
            else:
                d.text((px, y), ln, font=bf, fill=_blend(fg, bg, 0.92))
            y += lh
        y += gap
    if outro:
        oasc, odesc = of.getmetrics()
        for ln in owrap:
            d.text((x, y), ln, font=of, fill=fg)
            ow = d.textlength(ln, font=of)
            uy = y + oasc + odesc * 0.55 + 8   # 글자 아래로 충분히 내림
            _wavy(d, x, x + ow, uy, accent, amp=2.6, width=7, period=26)
            y += olh

    # 본문 폰트가 크게 잡혀 아래쪽에 여유가 남으면 관련 태그로 채움
    leftover = bottom - y
    if leftover > 90:
        tags = [t.lstrip("#") for t in item.get("extra_hashtags", [])[:3]]
        _tag_row(d, W / 2, y + min(leftover - 66, 40), max_w, tags, _font(Fr, 28), fg, bg)

    _footer(d, cfg, th, item, part, parts)
    return img


def _split_units(units: list[str]) -> list[list[str]]:
    if len(units) <= 6:
        return [units]
    half = (len(units) + 1) // 2
    return [units[:half], units[half:]]


def render_item(item: dict, out_dir: Path, cfg: dict | None = None) -> list[Path]:
    cfg = cfg or load_settings()
    body = item.get("body", {"type": "text", "text": ""})
    if body.get("type") == "text":
        groups = [[body.get("text", "")]]
    else:
        groups = _split_units(list(body.get("items", [])))

    out_dir.mkdir(parents=True, exist_ok=True)
    imgs = [_cover(item, cfg)]
    for i, g in enumerate(groups):
        imgs.append(_content(item, cfg, g, i + 1, len(groups)))

    paths: list[Path] = []
    for i, img in enumerate(imgs):
        p = out_dir / f"{i + 1}.jpg"  # Instagram 발행 API 는 JPEG 만 허용
        img.convert("RGB").save(p, "JPEG", quality=92, subsampling=1, optimize=True)
        paths.append(p)
    return paths


# ---------- CLI ----------
def _find(spec: str) -> dict:
    items = load_all_items()
    if "#" in spec:
        return items[int(spec.split("#", 1)[1])]
    for it in items:
        if it["slug"] == spec:
            return it
    raise SystemExit(f"항목을 찾을 수 없음: {spec}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview")
    ap.add_argument("--preview-all", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    cfg = load_settings()

    if args.preview_all:
        base = OUTPUT_DIR / "preview"
        if base.exists():
            shutil.rmtree(base)
        for it in load_all_items():
            paths = render_item(it, base / it["slug"], cfg)
            print(f"{it['slug']:26s} {len(paths)}장")
        print(f"\n미리보기: {base}")
        return

    if args.preview:
        it = _find(args.preview)
        out = Path(args.out) if args.out else OUTPUT_DIR / "preview" / it["slug"]
        for p in render_item(it, out, cfg):
            print(" ", p)
        return

    ap.print_help()


if __name__ == "__main__":
    main()
