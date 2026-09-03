"""문구 항목 1개를 '잘 꾸민 카드 한 장'(JPG)으로 렌더링한다.

레이아웃 (위 -> 아래):
  키커 칩  ·  제목(키워드 형광펜 강조)  ·  강조 바
  본문(번호 단계 / 불릿 / 문단)
  아웃트로 박스(저장 유도)  ·  하단 핸들/출처

내용이 많으면 자동으로 2장까지 나눈다(본문 항목을 나눠 담음).

사용:
  python -m src.render --preview "content/bank_A.json#0"
  python -m src.render --preview-all
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import FONT_DIR, OUTPUT_DIR, load_all_items, load_settings


# ---------- 색/폰트 유틸 ----------
def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def _blend(fg: str, bg: str, a: float) -> tuple[int, int, int]:
    f, b = _rgb(fg), _rgb(bg)
    return tuple(round(f[i] * a + b[i] * (1 - a)) for i in range(3))  # type: ignore


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> list[str]:
    """'\\n' 은 강제 줄바꿈. 그 외에는 공백 우선, 안 되면 글자 단위로 max_w 안에 맞춤."""
    out: list[str] = []
    for para in text.split("\n"):
        if draw.textlength(para, font=font) <= max_w:
            out.append(para)
            continue
        cur = ""
        for w in para.split(" "):
            trial = w if not cur else cur + " " + w
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
                continue
            if cur:
                out.append(cur)
            if draw.textlength(w, font=font) <= max_w:
                cur = w
            else:
                piece = ""
                for ch in w:
                    if draw.textlength(piece + ch, font=font) <= max_w:
                        piece += ch
                    else:
                        out.append(piece)
                        piece = ch
                cur = piece
        out.append(cur)
    return out


def _fit_title(draw, text, font_name, max_w, max_h, sizes, line_ratio=1.24):
    """제목: 명시한 줄바꿈(\\n)이 그대로 유지되는 가장 큰 크기를 우선.
    (어느 줄이 너무 길어 강제로 더 접히면 그 크기는 건너뜀)"""
    explicit = text.split("\n")
    best_clean = None   # 강제 줄바꿈 없이 높이도 맞는 것
    best_any = None      # 최소한 높이는 맞는 것
    for s in sizes:
        f = _font(font_name, s)
        lines = _wrap(draw, text, f, max_w)
        asc, desc = f.getmetrics()
        lh = int((asc + desc) * line_ratio)
        if lh * len(lines) > max_h:
            break
        best_any = (f, lines, lh)
        if len(lines) == len(explicit):
            best_clean = (f, lines, lh)
    if best_clean:
        return best_clean
    if best_any:
        return best_any
    f = _font(font_name, sizes[0])
    lines = _wrap(draw, text, f, max_w)
    asc, desc = f.getmetrics()
    return (f, lines, int((asc + desc) * line_ratio))


# ---------- 본문 블록 ----------
def _body_units(body: dict) -> tuple[str, list[str]]:
    t = body.get("type", "steps")
    if t == "text":
        return "text", [body.get("text", "")]
    return t, list(body.get("items", []))


def _measure_body(draw, units, btype, font_name_reg, font_name_bold, size,
                  max_w, x0) -> tuple[list, float, dict]:
    bf = _font(font_name_reg, size)
    asc, desc = bf.getmetrics()
    lh = int((asc + desc) * 1.32)
    badge = round(size * 1.9) if btype == "steps" else round(size * 0.62)
    text_indent = (badge + 26) if btype != "text" else 0
    inner_w = max_w - text_indent
    gap = round(size * 1.05)
    blocks = []
    total = 0.0
    for u in units:
        lines = _wrap(draw, u, bf, inner_w)
        bh = lh * len(lines)
        blocks.append(lines)
        total += bh + gap
    total = max(0.0, total - gap)
    meta = {"lh": lh, "badge": badge, "text_indent": text_indent, "gap": gap,
            "font": bf, "font_bold": _font(font_name_bold, max(size - 1, 12))}
    return blocks, total, meta


def _draw_body(d, x, y, units, blocks, btype, meta, fg, accent, bg):
    lh, badge, indent, gap = meta["lh"], meta["badge"], meta["text_indent"], meta["gap"]
    bf, bnf = meta["font"], meta["font_bold"]
    asc, _ = bf.getmetrics()
    for i, lines in enumerate(blocks):
        by = y
        if btype == "steps":
            cy = by + asc / 2
            d.ellipse([x, cy - badge / 2, x + badge, cy + badge / 2], fill=accent)
            num = str(i + 1)
            nf = _font(bnf.path, round(badge * 0.52))
            nb = d.textbbox((0, 0), num, font=nf)
            d.text((x + (badge - (nb[2] - nb[0])) / 2 - nb[0],
                    cy - (nb[3] - nb[1]) / 2 - nb[1]), num, font=nf, fill=bg)
        elif btype == "bullets":
            cy = by + asc / 2
            d.ellipse([x + 2, cy - badge / 2, x + 2 + badge, cy + badge / 2], fill=accent)
        for ln in lines:
            d.text((x + indent, by), ln, font=bf, fill=fg)
            by += lh
        y = by + gap
    return y


# ---------- 카드 1장 ----------
def _render_one(item: dict, cfg: dict, units: list[str], part: int, parts: int) -> Image.Image:
    W, H = cfg["size"]
    m = cfg.get("margin", 80)
    th = cfg["tracks"][item["track"]]
    bg, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#999999")
    F = cfg["fonts"]
    btype = item.get("body", {}).get("type", "steps")

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    x = m
    max_w = W - 2 * m
    y = m

    # 키커 칩
    kicker = item.get("kicker") or th.get("name", "")
    if parts > 1:
        kicker = f"{kicker}  ({part}/{parts})"
    if kicker:
        kf = _font(F["bold"], 27)
        tw = d.textlength(kicker, font=kf)
        ph, pv = 22, 13
        ch = 27 + pv * 2
        d.rounded_rectangle([x, y, x + tw + ph * 2, y + ch], radius=ch // 2, fill=accent)
        d.text((x + ph, y + pv - 2), kicker, font=kf, fill=bg)
        y += ch + 40

    # 제목 (part 1 에만 크게, 이후 장은 작게)
    title = item["title"]
    if part == 1:
        tf, tlines, tlh = _fit_title(d, title, F["bold"], max_w, 440,
                                     list(range(54, 90, 2)))
    else:
        tf, tlines, tlh = _fit_title(d, title, F["bold"], max_w, 240,
                                     list(range(40, 60, 2)))
    hl = item.get("title_highlight")
    for ln in tlines:
        if hl and hl in ln:
            pre = ln[:ln.index(hl)]
            px = x + d.textlength(pre, font=tf)
            hw = d.textlength(hl, font=tf)
            asc, _ = tf.getmetrics()
            ub = round(tf.size * 0.11)          # 밑줄 두께
            uy = y + asc + round(tf.size * 0.06)
            d.rounded_rectangle([px - 2, uy, px + hw + 2, uy + ub],
                                radius=ub // 2, fill=_blend(accent, bg, 0.55))
        d.text((x, y), ln, font=tf, fill=fg)
        y += tlh
    y += 26

    # 강조 바
    d.rounded_rectangle([x, y, x + 88, y + 7], radius=3, fill=accent)
    y += 7 + 46

    # 하단 구역 계산
    footer_y = H - 54
    outro = item.get("outro") if part == parts else None
    if outro:
        outro_bottom = H - 96
        outro_h = 128
        outro_top = outro_bottom - outro_h
        body_bottom = outro_top - 28
    else:
        body_bottom = H - 96
    avail_h = body_bottom - y

    # 본문: 큰 폰트부터 줄여가며 맞춤
    blocks = meta = None
    total = 0.0
    for s in range(46, 27, -2):
        blocks, total, meta = _measure_body(d, units, btype, F["regular"], F["bold"],
                                            s, max_w, x)
        if total <= avail_h:
            break
    # 남는 공간이 있으면 본문 블록을 세로 중앙에 (너무 아래로 쏠리지 않게 최대 90px)
    if total < avail_h:
        y += min((avail_h - total) / 2, 90)
    _draw_body(d, x, y, units, blocks, btype, meta, fg, accent, bg)

    # 아웃트로 박스
    if outro:
        d.rounded_rectangle([x, outro_top, W - m, outro_bottom], radius=20,
                            fill=_blend(accent, bg, 0.12))
        of = _font(F["bold"], 33)
        ow = d.textlength(outro, font=of)
        of_lines = _wrap(d, outro, of, max_w - 64)
        oy = outro_top + (outro_h - len(of_lines) * (of.getmetrics()[0] + of.getmetrics()[1])) / 2
        for ln in of_lines:
            lw = d.textlength(ln, font=of)
            d.text(((W - lw) / 2, oy), ln, font=of, fill=_blend(accent, bg, 0.95))
            oy += of.getmetrics()[0] + of.getmetrics()[1]

    # 하단: 출처(좌) / 핸들(우)
    sf = _font(F["regular"], 25)
    src = item.get("source")
    if src:
        d.text((x, footer_y), src, font=sf, fill=sub)
    handle = cfg.get("handle", "@your_handle")
    d.text((W - m - d.textlength(handle, font=sf), footer_y), handle, font=sf, fill=sub)

    return img


def _split_units(units: list[str], max_first: int = 4) -> list[list[str]]:
    """항목이 너무 많으면 두 장으로. (지금은 5개 이하면 1장)"""
    if len(units) <= 5:
        return [units]
    half = (len(units) + 1) // 2
    return [units[:half], units[half:]]


def render_item(item: dict, out_dir: Path, cfg: dict | None = None) -> list[Path]:
    cfg = cfg or load_settings()
    btype, units = _body_units(item.get("body", {"type": "text", "text": ""}))
    groups = _split_units(units) if btype != "text" else [units]
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
