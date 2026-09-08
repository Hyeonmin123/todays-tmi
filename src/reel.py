"""항목 1개를 릴스용 '후킹 전용' 세로 영상(mp4)으로 만든다.

  커버(제목=질문, 물결 지글거림) → 왼쪽으로 페이지 넘김 → 핵심 한 줄(outro, 크게 팝인).
  약 6초. 9:16 (1080x1920), H.264 / AAC. 상세 설명은 캡션·캐러셀이 담당.

오디오: settings.reel_audio(mp3 경로) 있으면 사용, 없으면 무음.
ffmpeg 는 imageio-ffmpeg 번들 바이너리 사용(시스템 설치 불필요).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .common import ROOT, load_settings
from .render import _blend, _dot_grid, _fit, _font, _marker, _safe_title, _wavy, _wrap

W, H = 1080, 1920
CW, CH = 1080, 1350
CARD_Y = (H - CH) // 2
FPS = 30
COVER_SEC = 3.0
PAYOFF_SEC = 3.6
XFADE = 0.45
JITTER_AMP = 2.6
JITTER_HOLD = 8
FADE_IN_F = 11             # 페이오프 텍스트가 나타나는 프레임 수


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _tall_bg(cfg):
    th = cfg["tracks"]["A"]
    bg, sub = th["bg"], th.get("sub", "#8A7A5C")
    img = Image.new("RGB", (W, H), bg)
    _dot_grid(ImageDraw.Draw(img), W, H, _blend(sub, bg, 0.16))
    return img


def _cover_layers(item: dict, cfg: dict):
    """(배경 RGB, 제목 RGBA). 제목만 프레임마다 물결 왜곡."""
    th = cfg["tracks"][item["track"]]
    bg, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#8A7A5C")
    m = cfg.get("margin", 90)
    Ft = cfg["fonts"].get("title", cfg["fonts"]["bold"])
    Fb, Fr = cfg["fonts"]["bold"], cfg["fonts"]["regular"]

    base = _tall_bg(cfg)
    d = ImageDraw.Draw(base)
    title = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(title)
    x = m

    d.text((m, CARD_Y + m), item.get("kicker") or th.get("name", ""),
           font=_font(Fb, 32), fill=sub)

    tf, lines, tlh = _fit(d, item["title"], Ft, W - 2 * m, 700, range(66, 138, 2), ratio=1.22)
    y = (H - tlh * len(lines)) / 2 - 30
    asc = tf.getmetrics()[0]
    for ln in _safe_title(item["title"]).split("\n"):
        lw = d.textlength(ln, font=tf)
        mk = _marker(int(lw + 26), int(asc * 0.60), accent)
        base.paste(mk, (int(x - 12), int(y + asc * 0.24)), mk)
        td.text((x, y), ln, font=tf, fill=fg)
        y += tlh

    hnf = _font(Fr, 26)
    handle = cfg.get("handle", "@your_handle")
    d.text((W - m - d.textlength(handle, font=hnf), H - CARD_Y // 2), handle,
           font=hnf, fill=sub)
    return np.asarray(base), np.asarray(title)


def _payoff_layers(item: dict, cfg: dict):
    """(배경 RGB, 핵심문구 RGBA). outro 를 크게. 텍스트만 팝인 + 지글거림."""
    th = cfg["tracks"][item["track"]]
    bg, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#8A7A5C")
    m = cfg.get("margin", 90)
    Ft = cfg["fonts"].get("title", cfg["fonts"]["bold"])
    Fb, Fr = cfg["fonts"]["bold"], cfg["fonts"]["regular"]

    base = _tall_bg(cfg)
    d = ImageDraw.Draw(base)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    d.text((m, CARD_Y + m), item.get("kicker") or th.get("name", ""),
           font=_font(Fb, 32), fill=sub)
    # 상단 작은 제목 리캡
    rf = _font(Ft, 44)
    ry = CARD_Y + m + 60
    for ln in _wrap(d, _safe_title(item["title"].replace("\n", " ")), rf, W - 2 * m):
        d.text((m, ry), ln, font=rf, fill=_blend(fg, bg, 0.55))
        ry += int(rf.size * 1.3)

    text = item.get("outro") or item["title"].replace("\n", " ")
    of, olines, olh = _fit(d, text, Ft, W - 2 * m, 560, range(58, 100, 2), ratio=1.24)
    oy = H * 0.40 - olh * len(olines) / 2       # 화면 상단~중앙 쪽으로
    oasc = of.getmetrics()[0]
    for ln in olines:
        lw = ld.textlength(ln, font=of)
        mk = _marker(int(lw + 24), int(oasc * 0.58), accent)
        base.paste(mk, (int((W - lw) / 2 - 12), int(oy + oasc * 0.26)), mk)
        ld.text(((W - lw) / 2, oy), ln, font=of, fill=fg)
        oy += olh

    # "자세한 내용은 본문에" 안내 — 핵심문구 바로 아래, 안전 구역(하단 UI 위)
    hy = oy + 46
    hint = "자세한 이야기는 본문(캡션)에 정리했어요"
    hf = _font(Fb, 33)
    hw = d.textlength(hint, font=hf)
    hx = (W - hw) / 2
    d.text((hx, hy), hint, font=hf, fill=_blend(fg, bg, 0.9))
    _wavy(d, hx, hx + hw, hy + hf.getmetrics()[0] + 6, accent, amp=3.0, width=7, period=26)
    arrow = "본문 펼쳐서 전체 내용 보기 ↓"
    af = _font(Fb, 27)
    d.text(((W - d.textlength(arrow, font=af)) / 2, hy + 52), arrow, font=af, fill=sub)
    return np.asarray(base), np.asarray(layer)


def _smooth_noise(gh: int, gw: int, rng) -> np.ndarray:
    g = rng.standard_normal((gh, gw)).astype(np.float32)
    im = Image.fromarray(((g - g.min()) / (np.ptp(g) + 1e-6) * 255).astype(np.uint8))
    a = np.asarray(im.resize((W, H), Image.BICUBIC), dtype=np.float32) / 255.0
    return a * 2.0 - 1.0


def _render_frames(bg: np.ndarray, layer: np.ndarray, out_dir: Path, prefix: str,
                   n: int, fade_in: int = 0, seed: int = 7) -> None:
    """layer(RGBA) 에 지글거림(boil) + 선택적 페이드인/팝인을 줘 프레임 저장."""
    rng = np.random.default_rng(seed)
    K = 6
    dxs = [_smooth_noise(22, 40, rng) for _ in range(K)]
    dys = [_smooth_noise(22, 40, rng) for _ in range(K)]
    ys, xs = np.mgrid[0:H, 0:W]
    bgf = bg.astype(np.float32)
    cy, cx = H / 2, W / 2
    for f in range(n):
        pos = f / JITTER_HOLD
        i = int(pos) % K
        u = pos - int(pos)
        u = u * u * (3 - 2 * u)
        dx = (dxs[i] * (1 - u) + dxs[(i + 1) % K] * u) * JITTER_AMP
        dy = (dys[i] * (1 - u) + dys[(i + 1) % K] * u) * JITTER_AMP
        # 팝인: 처음 fade_in 프레임 동안 살짝 확대 + 투명도 상승
        if fade_in and f < fade_in:
            p = f / fade_in
            p = p * p * (3 - 2 * p)
            alpha_mul = p
            scale = 0.94 + 0.06 * p
            dx = dx + (xs - cx) * (1 / scale - 1)
            dy = dy + (ys - cy) * (1 / scale - 1)
        else:
            alpha_mul = 1.0
        sy = np.clip((ys + dy).round().astype(np.int32), 0, H - 1)
        sx = np.clip((xs + dx).round().astype(np.int32), 0, W - 1)
        warped = layer[sy, sx]
        a = warped[:, :, 3:4].astype(np.float32) / 255.0 * alpha_mul
        frame = bgf * (1 - a) + warped[:, :, :3].astype(np.float32) * a
        Image.fromarray(frame.astype(np.uint8)).save(out_dir / f"{prefix}_{f:04d}.png")


def render_reel(item: dict, out_dir: Path, cfg: dict | None = None) -> Path:
    cfg = cfg or load_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    frm = out_dir / "_frames"
    frm.mkdir(exist_ok=True)

    n_cov = int(COVER_SEC * FPS)
    n_pay = int(PAYOFF_SEC * FPS)
    cbg, ctitle = _cover_layers(item, cfg)
    _render_frames(cbg, ctitle, frm, "cov", n_cov, fade_in=0, seed=7)
    pbg, ptext = _payoff_layers(item, cfg)
    _render_frames(pbg, ptext, frm, "pay", n_pay, fade_in=FADE_IN_F, seed=13)

    mp4 = out_dir / "reel.mp4"
    ff = _ffmpeg()
    dur = COVER_SEC + PAYOFF_SEC - XFADE
    offset = n_cov / FPS - XFADE

    vf = (
        f"[0:v]fps={FPS},settb=1/{FPS},format=yuv420p[cov];"
        f"[1:v]fps={FPS},settb=1/{FPS},format=yuv420p[pay];"
        f"[cov][pay]xfade=transition=slideleft:duration={XFADE}:offset={offset:.2f}[v]"
    )
    cmd = [ff, "-y",
           "-framerate", str(FPS), "-i", str(frm / "cov_%04d.png"),
           "-framerate", str(FPS), "-i", str(frm / "pay_%04d.png")]

    audio = cfg.get("reel_audio", "")
    apath = (ROOT / audio) if audio else None
    if apath and apath.exists():
        cmd += ["-stream_loop", "-1", "-i", str(apath)]
        amap = ["-map", "2:a", "-af",
                f"afade=t=in:d=0.4,afade=t=out:st={dur - 0.8:.1f}:d=0.8,volume=0.55"]
    else:
        cmd += ["-f", "lavfi", "-t", str(dur + 1), "-i", "anullsrc=r=44100:cl=stereo"]
        amap = ["-map", "2:a"]

    cmd += ["-filter_complex", vf, "-map", "[v]", *amap,
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
    it = next(x for x in load_all_items() if x["slug"] == slug)
    p = render_reel(it, OUTPUT_DIR / "preview" / slug)
    print("ok ->", p, p.stat().st_size, "bytes")
