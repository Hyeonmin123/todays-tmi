"""문구 항목 1개를 '노트/필기' 스타일 카드(JPG) 한 장으로 렌더링한다.

- 따뜻한 종이색 + 점 그리드 배경
- 손글씨체(Gaegu), 제목 키워드에 형광펜, 손그림 밑줄, 링 불릿
- 위→아래로 내용이 카드를 꽉 채우도록 본문 글씨/간격을 자동 확대

사용:
  python -m src.render --preview "content/bank_A.json#0"
  python -m src.render --preview-all
"""
from __future__ import annotations

import argparse
import math
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


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_w: float) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if d.textlength(para, font=font) <= max_w:
            out.append(para)
            continue
        cur = ""
        for w in para.split(" "):
            t = (cur + " " + w).strip()
            if d.textlength(t, font=font) <= max_w:
                cur = t
            else:
                if cur:
                    out.append(cur)
                cur = w
        out.append(cur)
    return out


def _fit_title(d, text, fname, max_w, max_h, sizes):
    """명시한 줄바꿈이 유지되면서 max_h 안에 드는 가장 큰 크기."""
    exp = text.split("\n")
    best = None
    for s in sizes:
        f = _font(fname, s)
        lines = _wrap(d, text, f, max_w)
        asc, desc = f.getmetrics()
        lh = int((asc + desc) * 1.16)
        if len(lines) == len(exp) and lh * len(lines) <= max_h:
            best = (f, lines, lh)
    if best:
        return best
    f = _font(fname, sizes[0])
    lines = _wrap(d, text, f, max_w)
    asc, desc = f.getmetrics()
    return (f, lines, int((asc + desc) * 1.16))


def _dot_grid(d: ImageDraw.ImageDraw, w: int, h: int, color, step: int = 46):
    for gx in range(step // 2, w, step):
        for gy in range(step // 2, h, step):
            d.ellipse([gx - 1.4, gy - 1.4, gx + 1.4, gy + 1.4], fill=color)


def _wavy(d: ImageDraw.ImageDraw, x0: float, x1: float, y: float, color,
          amp: float = 2.4, width: int = 5, period: float = 34):
    pts = []
    x = x0
    while x <= x1:
        pts.append((x, y + math.sin((x - x0) / period * math.pi) * amp))
        x += 6
    if len(pts) >= 2:
        d.line(pts, fill=color, width=width, joint="curve")


def _dot(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def _marker(width: int, height: int, color) -> Image.Image:
    """형광펜 한 획 (반투명, 끝이 살짝 둥근). 회전시켜 붙일 것."""
    pad = 6
    im = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    r, g, b = _rgb(color) if isinstance(color, str) else color
    dd.rounded_rectangle([pad, pad, pad + width, pad + height],
                         radius=height // 2, fill=(r, g, b, 150))
    return im.rotate(-1.2, expand=True, resample=Image.BICUBIC)


# ---------- 카드 ----------
def _render_one(item: dict, cfg: dict, units: list[str], part: int, parts: int) -> Image.Image:
    W, H = cfg["size"]
    m = cfg.get("margin", 90)
    th = cfg["tracks"][item["track"]]
    bg, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#8A7A5C")
    Fb, Fr = cfg["fonts"]["bold"], cfg["fonts"]["regular"]

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    _dot_grid(d, W, H, _blend(sub, bg, 0.16))
    x = m
    max_w = W - 2 * m

    # 키커
    kicker = item.get("kicker") or th.get("name", "")
    if parts > 1:
        kicker = f"{kicker}  ({part}/{parts})"
    kf = _font(Fb, 30)
    d.text((x, m), kicker, font=kf, fill=sub)
    y = m + 30 + 34

    # 제목 (+ 형광펜)
    tsize = range(46, 84, 2) if part == 1 else range(38, 60, 2)
    tf, tlines, tlh = _fit_title(d, item["title"], Fb, max_w, 380, tsize)
    hl = item.get("title_highlight")
    for ln in tlines:
        if hl and hl in ln and d.textlength(ln, font=tf) <= max_w:
            pre = d.textlength(ln[:ln.index(hl)], font=tf)
            hw = d.textlength(hl, font=tf)
            asc, _ = tf.getmetrics()
            mk = _marker(int(hw + 20), int(asc * 0.60), accent)
            img.paste(mk, (int(x + pre - 12), int(y + asc * 0.40)), mk)
        d.text((x, y), ln, font=tf, fill=fg)
        y += tlh
    y += 12
    _wavy(d, x, x + min(max_w * 0.46, 300), y, sub, amp=2.6, width=4)
    y += 40

    # 본문 + 아웃트로가 아래 여백까지 꽉 차도록 크기·간격 자동 확대
    footer_h = 44
    bottom = H - m - footer_h
    avail = bottom - y
    outro = item.get("outro") if part == parts else None

    chosen = None
    for bs in range(52, 27, -2):
        bf = _font(Fr, bs)
        a1, d1 = bf.getmetrics()
        lh = int((a1 + d1) * 1.34)
        wrapped = [_wrap(d, u, bf, max_w - 46) for u in units]
        body_core = sum(lh * len(w) for w in wrapped)
        of = _font(Fb, max(bs - 3, 26))
        a2, d2 = of.getmetrics()
        olh = int((a2 + d2) * 1.3)
        owrap = _wrap(d, outro, of, max_w) if outro else []
        outro_core = olh * len(owrap)
        n_gaps = len(units) + (1 if outro else 0)
        if body_core + outro_core + 18 * n_gaps <= avail or bs == 30:
            chosen = (bf, lh, wrapped, of, olh, owrap, body_core, outro_core, n_gaps)
            break

    bf, lh, wrapped, of, olh, owrap, body_core, outro_core, n_gaps = chosen
    slack = avail - body_core - outro_core
    gap = max(20, min(slack / max(n_gaps, 1), 110))

    for w in wrapped:
        cy = y + bf.getmetrics()[0] * 0.52
        _dot(d, x + 8, cy, 7, sub)
        for ln in w:
            d.text((x + 46, y), ln, font=bf, fill=_blend(fg, bg, 0.92))
            y += lh
        y += gap

    if outro:
        for ln in owrap:
            d.text((x, y), ln, font=of, fill=fg)
            ow = d.textlength(ln, font=of)
            _wavy(d, x, x + ow, y + of.getmetrics()[0] + 6, accent, amp=3.2,
                  width=8, period=26)
            y += olh

    # 하단: 출처(좌) / 핸들(우)
    hf = _font(Fr, 24)
    fy = H - m - 2
    src = item.get("source")
    if src:
        while src and d.textlength(src, font=hf) > max_w * 0.60:
            src = src[:-1]
        d.text((x, fy), src, font=hf, fill=sub)
    handle = cfg.get("handle", "@your_handle")
    d.text((W - m - d.textlength(handle, font=hf), fy), handle, font=hf, fill=sub)
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
    paths: list[Path] = []
    for i, g in enumerate(groups):
        img = _render_one(item, cfg, g, i + 1, len(groups))
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
