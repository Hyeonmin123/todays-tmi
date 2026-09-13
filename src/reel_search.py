"""항목 1개를 릴스용 '검색창 UI' 세로 영상(mp4)으로 만든다. (프로덕션)

  통념을 검색어로 타이핑 -> 탭 -> 로딩 -> 자동완성 -> 검색 결과 카드로 정답 등장
  (부가 설명 + 출처 포함) -> 관련 검색 칩 -> 팔로우 유도 -> 함께 찾아본 질문.
  브랜드 폰트(DoHyeon/Gaegu)는 카드 속 정답에만 쓰고, 검색창/상태바 같은
  '앱 UI' 요소는 Pretendard(고딕)로 그려 실제 화면 캡처처럼 보이게 한다.
  실제 검색엔진 로고/워드마크는 흉내내지 않는다(범용 검색 UI).

  검색어는 item["search_query"] 를 쓰고, 없으면 제목 첫 줄에서 자동으로 뽑는다
  (_derive_query). run_daily.py 가 render_reel(item, out_dir, cfg) 로 호출.

사용(수동 미리보기):
  python -m src.reel_search <slug> ["검색어 오버라이드"]
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .common import load_settings
from .render import _blend, _dot_grid, _fit, _font, _marker, _rgb, _wavy, _wrap

W, H = 1080, 1920
FPS = 30
PT_BOLD = "Pretendard-Bold.otf"
PT_SEMI = "Pretendard-SemiBold.otf"
PT_REG = "Pretendard-Regular.otf"

TYPE_SEC = 1.4
PAUSE_SEC = 0.18
TAP_SEC = 0.22
LOAD_SEC = 0.5
CARD_IN_SEC = 0.32
HINT_DELAY_SEC = 0.55
HINT_FADE_SEC = 0.32
CHIPS_DELAY_SEC = 0.22
CHIP_STAGGER_SEC = 0.07
CHIP_FADE_SEC = 0.22
FOLLOW_DELAY_SEC = 0.30
FOLLOW_FADE_SEC = 0.28
PAA_DELAY_SEC = 0.30
PAA_STAGGER_SEC = 0.14
PAA_FADE_SEC = 0.24
TAIL_HOLD_SEC = 0.9
SUGG_APPEAR_AT = 0.4     # 검색어의 이 비율만큼 타이핑되면 자동완성 목록 등장
SUGG_FADE_IN = 8         # 프레임
SUGG_FADE_OUT = 6


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _icon_search(d, cx, cy, r, color, width=5):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)
    hx, hy = cx + r * 0.68, cy + r * 0.68
    d.line([hx, hy, hx + r * 0.68, hy + r * 0.68], fill=color, width=width + 1)


def _icon_wifi(d, cx, cy, color):
    d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=color)
    for r in (9, 15):
        d.arc([cx - r, cy - r, cx + r, cy + r], start=215, end=325, fill=color, width=3)


def _icon_battery(d, x, y, color):
    w, h = 46, 22
    d.rounded_rectangle([x, y, x + w, y + h], radius=4, outline=color, width=2)
    d.rectangle([x + w + 2, y + h * 0.28, x + w + 5, y + h * 0.72], fill=color)
    d.rounded_rectangle([x + 3, y + 3, x + w - 3, y + h - 3], radius=2, fill=color)


def _icon_signal(d, x, y, color):
    bw, gap = 5, 3
    for i, hgt in enumerate((7, 11, 15, 19)):
        bx = x + i * (bw + gap)
        d.rectangle([bx, y + 19 - hgt, bx + bw, y + 19], fill=color)


def _chip_rows(probe, labels, font, max_w, pad_x=24, gap=14):
    """칩 라벨을 max_w 안에서 줄바꿈. [[(label, width), ...], ...] 반환."""
    rows: list[list[tuple[str, float]]] = []
    cur: list[tuple[str, float]] = []
    cur_w = 0.0
    for lb in labels:
        w = probe.textlength(lb, font=font) + pad_x * 2
        add = w if not cur else gap + w
        if cur and cur_w + add > max_w:
            rows.append(cur)
            cur, cur_w = [], 0.0
            add = w
        cur.append((lb, w))
        cur_w += add
    if cur:
        rows.append(cur)
    return rows


def _sugg_row(d, x, y, w, h, text, font, icon_color, text_color, divider_color, alpha, draw_divider):
    a = int(255 * alpha)
    if a <= 0:
        return
    _icon_search(d, x + 30, y + h / 2, 12, (*_rgb(icon_color), a), width=3)
    d.text((x + 58, y + (h - font.size) / 2 - 6), text, font=font, fill=(*_rgb(text_color), a))
    if draw_divider:
        d.line([x + 58, y + h, x + w, y + h], fill=(*_rgb(divider_color), int(a * 0.5)), width=1)


def _paa_row(d, x, y, w, h, text, font, text_color, chev_color, border_color, fill_color, alpha):
    a = int(255 * alpha)
    if a <= 0:
        return
    d.rounded_rectangle([x, y, x + w, y + h], radius=18,
                         fill=(*_rgb(fill_color), int(a * 0.6)),
                         outline=(*_rgb(border_color), int(a * 0.5)), width=2)
    d.text((x + 28, y + (h - font.size) / 2 - 6), text, font=font, fill=(*_rgb(text_color), a))
    chx, chy = x + w - 44, y + h / 2 - 2
    d.line([chx - 9, chy - 5, chx, chy + 5, chx + 9, chy - 5],
           fill=(*_rgb(chev_color), a), width=3, joint="curve")


def _shadow(w, h, radius, blur=16, alpha=60):
    pad = blur * 2
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([pad, pad, pad + w, pad + h], radius=radius, fill=(0, 0, 0, alpha))
    return im.filter(ImageFilter.GaussianBlur(blur)), pad


_TRAILING_PARTICLES = ("에는", "에서", "이지만", "지만", "은", "는", "이", "가", "을", "를", "의")


def _derive_query(item: dict) -> str:
    """search_query 필드가 없을 때 제목 첫 줄에서 검색어 느낌으로 다듬어 뽑는다."""
    line1 = item["title"].split("\n")[0].strip()
    for p in _TRAILING_PARTICLES:
        if line1.endswith(p) and len(line1) > len(p) + 1:
            return line1[: -len(p)].strip()
    return line1


def render_reel(item: dict, out_dir: Path, cfg: dict | None = None, query: str | None = None) -> Path:
    cfg = cfg or load_settings()
    query = query or item.get("search_query") or _derive_query(item)
    out_dir.mkdir(parents=True, exist_ok=True)
    frm = out_dir / "_frames"
    frm.mkdir(exist_ok=True)

    th = cfg["tracks"][item["track"]]
    bg_hex, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#8A7A5C")
    m = cfg.get("margin", 90)
    Ft = cfg["fonts"].get("title", cfg["fonts"]["bold"])
    Fb = cfg["fonts"]["bold"]
    white = "#FFFFFF"

    base = Image.new("RGB", (W, H), bg_hex)
    bd = ImageDraw.Draw(base)
    # 아주 옅은 점 그리드 - 화면이 휑해 보이지 않게 + 브랜드 연속성
    _dot_grid(bd, W, H, _blend(sub, bg_hex, 0.10))
    # 상태바 (화면 캡처처럼 보이는 디테일)
    bd.text((m, 58), "9:41", font=_font(PT_SEMI, 30), fill=fg)
    _icon_signal(bd, W - m - 128, 60, fg)
    _icon_wifi(bd, W - m - 84, 70, fg)
    _icon_battery(bd, W - m - 56, 60, fg)

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # ---- 검색창 ----
    pill_y = int(H * 0.135)
    pill_h = 100
    pill_r = pill_h // 2
    pill_w = W - 2 * m
    qf = _font(PT_REG, 34)

    # ---- 자동완성 목록 (타이핑 중 빈 화면 채움) ----
    sugg_texts = [query, f"{query} 이유", f"{query} 총정리"]
    sugg_font = _font(PT_REG, 32)
    sugg_row_h = 78
    sugg_y0 = pill_y + pill_h + 14

    # ---- 결과 카드(정답 + 부가 설명 + 출처로 꽉 채움) ----
    outro = item.get("outro") or item["title"].replace("\n", " ")
    card_w = W - 2 * m
    pad = 40
    rf, rlines, rlh = _fit(probe, outro, Ft, card_w - 2 * pad, 480, range(52, 92, 2), ratio=1.24)
    rasc = rf.getmetrics()[0]
    label_h = 40

    detail_font = _font(PT_REG, 36)
    body_items = (item.get("body") or {}).get("items") or []
    detail_raw = body_items[0] if body_items else ""
    detail_wrapped = _wrap(probe, detail_raw, detail_font, card_w - 2 * pad) if detail_raw else []
    detail_lines = detail_wrapped[:2]
    if len(detail_wrapped) > 2:
        while detail_lines[-1] and probe.textlength(detail_lines[-1] + "…", font=detail_font) > card_w - 2 * pad:
            detail_lines[-1] = detail_lines[-1][:-1]
        detail_lines[-1] += "…"
    detail_lh = int(detail_font.size * 1.42)

    source_font = _font(PT_REG, 25)
    source_text = item.get("source", "")

    divider_gap = 26
    card_h = (pad + label_h + 18 + rlh * len(rlines)
              + (divider_gap + detail_lh * len(detail_lines) if detail_lines else 0)
              + (divider_gap + source_font.size + 6 if source_text else 0)
              + pad)
    card_x = m
    card_y_final = pill_y + pill_h + 46

    hint = "자세한 이야기는 본문(캡션)에 정리했어요"
    arrow = "본문 펼쳐서 전체 내용 보기 ↓"
    hf = _font(Fb, 32)
    af = _font(Fb, 26)
    hw = probe.textlength(hint, font=hf)
    hx = (W - hw) / 2
    hy = card_y_final + card_h + 60

    # ---- 관련 검색 칩 (해시태그 재활용) ----
    chip_labels = [h.lstrip("#") for h in item.get("extra_hashtags", [])[:5]]
    chips_label_y = hy + 116
    chip_font = _font(PT_REG, 30)
    chip_h = 62
    chip_rows_raw = _chip_rows(probe, chip_labels, chip_font, card_w) if chip_labels else []
    chip_rows = []  # [[(label, x, y, w), ...], ...]
    ry_cursor = chips_label_y + 44
    for row in chip_rows_raw:
        row_w = sum(w for _, w in row) + 16 * (len(row) - 1)
        rx = m + (card_w - row_w) / 2
        laid = []
        for lb, w in row:
            laid.append((lb, rx, ry_cursor, w))
            rx += w + 16
        chip_rows.append(laid)
        ry_cursor += chip_h + 20
    chips_bottom = ry_cursor - 20 if chip_rows else chips_label_y

    # ---- 팔로우 유도 칩 ----
    follow_text = "팔로우하면 매일 이런 게 옵니다"
    flf = _font(cfg["fonts"]["bold"], 32)
    fw = probe.textlength(follow_text, font=flf)
    follow_h = 84
    follow_w = fw + 72
    follow_x = (W - follow_w) / 2
    follow_y = chips_bottom + 72

    # ---- "사람들이 함께 찾아봤어요" 아코디언 2줄 (화면 하단까지 채움) ----
    paa_label = "사람들이 함께 찾아봤어요"
    paa_qs = ["이거 말고 또 신기한 사실 있어?", "다른 TMI 이야기도 보고 싶은데"]
    paa_font = _font(PT_REG, 30)
    paa_row_h = 92
    paa_gap = 20
    paa_label_y = follow_y + follow_h + 64
    paa_row_y0 = paa_label_y + 44

    shadow_im, shadow_pad = _shadow(card_w, card_h, 28)

    n_type = round(TYPE_SEC * FPS)
    n_pause = round(PAUSE_SEC * FPS)
    n_tap = round(TAP_SEC * FPS)
    n_load = round(LOAD_SEC * FPS)
    n_cardin = round(CARD_IN_SEC * FPS)
    n_hintdelay = round(HINT_DELAY_SEC * FPS)
    n_hintfade = round(HINT_FADE_SEC * FPS)
    n_chipsdelay = round(CHIPS_DELAY_SEC * FPS)
    n_chipstagger = round(CHIP_STAGGER_SEC * FPS)
    n_chipfade = round(CHIP_FADE_SEC * FPS)
    n_followdelay = round(FOLLOW_DELAY_SEC * FPS)
    n_followfade = round(FOLLOW_FADE_SEC * FPS)
    n_paadelay = round(PAA_DELAY_SEC * FPS)
    n_paastagger = round(PAA_STAGGER_SEC * FPS)
    n_paafade = round(PAA_FADE_SEC * FPS)
    n_tailhold = round(TAIL_HOLD_SEC * FPS)

    n_chips_total = sum(len(r) for r in chip_rows)
    chips_span = (n_chips_total - 1) * n_chipstagger + n_chipfade if n_chips_total else 0
    paa_span = (len(paa_qs) - 1) * n_paastagger + n_paafade

    total = (n_type + n_pause + n_tap + n_load + n_cardin + n_hintdelay + n_hintfade
             + n_chipsdelay + chips_span + n_followdelay + n_followfade
             + n_paadelay + paa_span + n_tailhold)
    sugg_start = round(SUGG_APPEAR_AT * n_type)

    icon_cx, icon_cy = m + 46, pill_y + pill_h // 2

    for f in range(total):
        frame = base.copy()
        d = ImageDraw.Draw(frame, "RGBA")

        # 검색창 껍데기(항상 존재)
        d.rounded_rectangle([m, pill_y, m + pill_w, pill_y + pill_h], radius=pill_r,
                             fill=white, outline=_blend(sub, bg_hex, 0.25), width=2)

        t = f
        if t < n_type:
            nchar = round((t / max(1, n_type)) * len(query))
            shown = query[:nchar]
            cursor_on = (t // 10) % 2 == 0
            _icon_search(d, icon_cx, icon_cy, 15, sub)
            d.text((m + 82, pill_y + (pill_h - qf.size) / 2 - 6), shown, font=qf, fill=fg)
            if cursor_on:
                cw = probe.textlength(shown, font=qf)
                cx0 = m + 82 + cw + 3
                d.line([cx0, pill_y + 24, cx0, pill_y + pill_h - 24], fill=fg, width=3)
            sp = min(1.0, max(0.0, (t - sugg_start) / SUGG_FADE_IN))
            for i, stext in enumerate(sugg_texts):
                _sugg_row(d, m, sugg_y0 + i * sugg_row_h, pill_w, sugg_row_h, stext, sugg_font,
                          sub, fg, sub, sp, i < len(sugg_texts) - 1)
            frame.save(frm / f"f_{f:04d}.png")
            continue
        t -= n_type

        if t < n_pause:
            _icon_search(d, icon_cx, icon_cy, 15, sub)
            d.text((m + 82, pill_y + (pill_h - qf.size) / 2 - 6), query, font=qf, fill=fg)
            for i, stext in enumerate(sugg_texts):
                _sugg_row(d, m, sugg_y0 + i * sugg_row_h, pill_w, sugg_row_h, stext, sugg_font,
                          sub, fg, sub, 1.0, i < len(sugg_texts) - 1)
            frame.save(frm / f"f_{f:04d}.png")
            continue
        t -= n_pause

        if t < n_tap:
            p = t / max(1, n_tap)
            scale = 1.0 + 0.5 * (1 - abs(p - 0.5) * 2)
            _icon_search(d, icon_cx, icon_cy, 15 * scale, accent, width=5)
            d.text((m + 82, pill_y + (pill_h - qf.size) / 2 - 6), query, font=qf, fill=fg)
            sp = 1.0 - min(1.0, p / 0.5)
            for i, stext in enumerate(sugg_texts):
                _sugg_row(d, m, sugg_y0 + i * sugg_row_h, pill_w, sugg_row_h, stext, sugg_font,
                          sub, fg, sub, sp, i < len(sugg_texts) - 1)
            frame.save(frm / f"f_{f:04d}.png")
            continue
        t -= n_tap

        if t < n_load:
            ang = (t / n_load) * 720
            r = 15
            d.arc([icon_cx - r, icon_cy - r, icon_cx + r, icon_cy + r],
                  start=ang, end=ang + 260, fill=accent, width=5)
            d.text((m + 82, pill_y + (pill_h - qf.size) / 2 - 6), query, font=qf, fill=_blend(fg, bg_hex, 0.55))
            frame.save(frm / f"f_{f:04d}.png")
            continue
        t -= n_load

        # ---- 카드 등장 ----
        _icon_search(d, icon_cx, icon_cy, 15, sub)
        d.text((m + 82, pill_y + (pill_h - qf.size) / 2 - 6), query, font=qf, fill=_blend(fg, bg_hex, 0.55))

        if t < n_cardin:
            p = t / max(1, n_cardin)
            p = p * p * (3 - 2 * p)
            offset = int(36 * (1 - p))
            alpha = p
        else:
            offset = 0
            alpha = 1.0
        cy = card_y_final + offset

        sh = shadow_im.copy()
        sh.putalpha(sh.split()[3].point(lambda a, al=alpha: int(a * al)))
        frame.paste(sh, (card_x - shadow_pad, int(cy - shadow_pad) + 8), sh)

        card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, card_w, card_h], radius=28, fill=(*_rgb(white), int(255 * alpha)))
        cd.ellipse([pad, pad + 6, pad + 16, pad + 22], fill=(*_rgb(accent), int(255 * alpha)))
        cd.text((pad + 28, pad), "오늘의 TMI · 빠른 답변", font=_font(PT_SEMI, 27),
                fill=(*_rgb(sub), int(255 * alpha)))
        ry = pad + label_h + 4
        for ln in rlines:
            lw = cd.textlength(ln, font=rf)
            lx = (card_w - lw) / 2
            mk = _marker(int(lw + 24), int(rasc * 0.58), accent)
            mk.putalpha(mk.split()[3].point(lambda a, al=alpha: int(a * al)))
            card.paste(mk, (int(lx - 12), int(ry + rasc * 0.26)), mk)
            cd.text((lx, ry), ln, font=rf, fill=(*_rgb(fg), int(255 * alpha)))
            ry += rlh

        if detail_lines:
            ry += divider_gap - 10
            cd.line([pad, ry, card_w - pad, ry], fill=(*_rgb(sub), int(255 * alpha * 0.25)), width=2)
            ry += 20
            for ln in detail_lines:
                cd.text((pad, ry), ln, font=detail_font, fill=(*_blend(fg, bg_hex, 0.72), int(255 * alpha)))
                ry += detail_lh

        if source_text:
            ry += divider_gap - 16
            cd.text((pad, ry), source_text, font=source_font, fill=(*_rgb(sub), int(255 * alpha * 0.85)))

        frame.paste(card, (card_x, int(cy)), card)

        if t >= n_cardin:
            lt = t - n_cardin
            if lt >= n_hintdelay:
                hp = min(1.0, (lt - n_hintdelay) / max(1, n_hintfade))
                hp = hp * hp * (3 - 2 * hp)
                if hp > 0:
                    col = tuple(int(c) for c in _blend(fg, bg_hex, 0.9)) + (int(255 * hp),)
                    d.text((hx, hy), hint, font=hf, fill=col)
                    _wavy(d, hx, hx + hw, hy + hf.getmetrics()[0] + 6,
                          (*_rgb(accent), int(255 * hp)), amp=3.0, width=7, period=26)
                    d.text(((W - d.textlength(arrow, font=af)) / 2, hy + 50), arrow,
                           font=af, fill=(*_rgb(sub), int(255 * hp)))

            chips_t = lt - (n_hintdelay + n_hintfade) - n_chipsdelay
            if chips_t >= 0 and chip_rows:
                d.text((m, chips_label_y - 34), "관련 검색", font=_font(PT_SEMI, 26), fill=sub)
                gi = 0
                for row in chip_rows:
                    for lb, cx0, cy0, cw0 in row:
                        cp = min(1.0, max(0.0, (chips_t - gi * n_chipstagger) / max(1, n_chipfade)))
                        cp = cp * cp * (3 - 2 * cp)
                        if cp > 0:
                            off = int(10 * (1 - cp))
                            a = int(255 * cp)
                            d.rounded_rectangle([cx0, cy0 + off, cx0 + cw0, cy0 + off + chip_h],
                                                 radius=chip_h // 2,
                                                 fill=(*_rgb(white), a),
                                                 outline=(*_rgb(sub), int(a * 0.4)), width=2)
                            tw = probe.textlength(lb, font=chip_font)
                            d.text((cx0 + (cw0 - tw) / 2, cy0 + off + (chip_h - chip_font.size) / 2 - 4),
                                   lb, font=chip_font, fill=(*_rgb(fg), a))
                        gi += 1

            follow_t = chips_t - chips_span - n_followdelay
            if follow_t >= 0:
                fp = min(1.0, follow_t / max(1, n_followfade))
                fp = fp * fp * (3 - 2 * fp)
                if fp > 0:
                    off = int(14 * (1 - fp))
                    a = int(255 * fp)
                    scale = 0.92 + 0.08 * fp
                    fw2, fh2 = follow_w * scale, follow_h * scale
                    fx2 = W / 2 - fw2 / 2
                    fy2 = follow_y + off + (follow_h - fh2) / 2
                    d.rounded_rectangle([fx2, fy2, fx2 + fw2, fy2 + fh2], radius=fh2 / 2,
                                         fill=(*_rgb(accent), a))
                    d.text((W / 2 - fw * scale / 2, fy2 + (fh2 - flf.size * scale) / 2 - 4),
                           follow_text, font=flf, fill=(*_rgb(fg), a))

            paa_t = follow_t - n_followfade - n_paadelay
            if paa_t >= 0:
                lp0 = min(1.0, paa_t / max(1, n_paafade))
                lp0 = lp0 * lp0 * (3 - 2 * lp0)
                if lp0 > 0:
                    col = (*_rgb(sub), int(255 * lp0))
                    d.text((m, paa_label_y), paa_label, font=_font(PT_SEMI, 28), fill=col)
                for i, q_text in enumerate(paa_qs):
                    rp = min(1.0, max(0.0, (paa_t - i * n_paastagger) / max(1, n_paafade)))
                    rp = rp * rp * (3 - 2 * rp)
                    if rp > 0:
                        ry0 = paa_row_y0 + i * (paa_row_h + paa_gap) + int(12 * (1 - rp))
                        _paa_row(d, m, ry0, card_w, paa_row_h, q_text, paa_font,
                                 fg, sub, sub, white, rp)

        frame.save(frm / f"f_{f:04d}.png")

    mp4 = out_dir / "reel_search.mp4"
    ff = _ffmpeg()
    dur = total / FPS
    cmd = [ff, "-y", "-framerate", str(FPS), "-i", str(frm / "f_%04d.png"),
           "-f", "lavfi", "-t", str(dur + 1), "-i", "anullsrc=r=44100:cl=stereo",
           "-t", f"{dur:.2f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
           "-movflags", "+faststart", "-shortest", str(mp4)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not mp4.exists():
        raise RuntimeError("ffmpeg 실패:\n" + (r.stderr or "")[-2500:])

    for p in frm.glob("*"):
        p.unlink()
    frm.rmdir()
    return mp4


if __name__ == "__main__":
    import sys
    from .common import OUTPUT_DIR, load_all_items
    slug = sys.argv[1] if len(sys.argv) > 1 else load_all_items()[0]["slug"]
    override = sys.argv[2] if len(sys.argv) > 2 else None
    it = next(x for x in load_all_items() if x["slug"] == slug)
    p = render_reel(it, OUTPUT_DIR / "preview" / ("_search_" + slug), query=override)
    print("ok ->", p, p.stat().st_size, "bytes")
