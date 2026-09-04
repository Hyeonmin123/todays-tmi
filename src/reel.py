"""항목 1개를 릴스용 세로 영상(mp4)으로 만든다.

  커버(제목이 물결처럼 꿀렁이는 모션) → 왼쪽으로 페이지 넘김 → 내용 카드(느린 줌).
  9:16 (1080x1920), 약 11초, H.264 / AAC.

오디오: settings.reel_audio(mp3 경로) 있으면 사용, 없으면 무음.
ffmpeg 는 imageio-ffmpeg 번들 바이너리 사용(시스템 설치 불필요).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .common import ROOT, load_settings
from .render import (_blend, _dot_grid, _fit, _font, _marker, _safe_title, render_item)

W, H = 1080, 1920
CW, CH = 1080, 1350          # 카드 크기
CARD_Y = (H - CH) // 2       # 카드가 놓이는 y
FPS = 30
COVER_SEC = 3.8
CONTENT_SEC = 8.0
XFADE = 0.55
JITTER_AMP = 2.6            # 제목 지글거림 최대 변위(px). 작을수록 미세
JITTER_HOLD = 8            # 몇 프레임마다 노이즈 필드 교체 (클수록 느리게 떨림)


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _tall_bg(cfg):
    th = cfg["tracks"]["A"]
    bg, sub = th["bg"], th.get("sub", "#8A7A5C")
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    _dot_grid(d, W, H, _blend(sub, bg, 0.16))
    return img, d


def _page_dots(d, cfg, idx, total=2):
    th = cfg["tracks"]["A"]
    accent, sub, bg = th["accent"], th.get("sub", "#8A7A5C"), th["bg"]
    gap = 26
    tot = total * 14 + (total - 1) * gap
    sx = (W - tot) // 2
    for i in range(total):
        c = accent if i == idx else _blend(sub, bg, 0.5)
        d.ellipse([sx + i * (14 + gap), H - 92, sx + i * (14 + gap) + 14, H - 78], fill=c)


def _cover_layers(item: dict, cfg: dict):
    """커버를 (배경 RGB, 제목 RGBA) 두 장으로. 제목만 프레임마다 물결 왜곡."""
    th = cfg["tracks"][item["track"]]
    bg, fg, accent, sub = th["bg"], th["fg"], th["accent"], th.get("sub", "#8A7A5C")
    m = cfg.get("margin", 90)
    Ft = cfg["fonts"].get("title", cfg["fonts"]["bold"])
    Fb, Fr = cfg["fonts"]["bold"], cfg["fonts"]["regular"]

    base, d = _tall_bg(cfg)
    title = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(title)
    x = m

    d.text((m, CARD_Y + m), item.get("kicker") or th.get("name", ""),
           font=_font(Fb, 30), fill=sub)
    inf = _font(Fr, 26)
    d.text((W - m - d.textlength("1 / 2", font=inf), CARD_Y + m + 2), "1 / 2",
           font=inf, fill=sub)

    tf, lines, tlh = _fit(d, item["title"], Ft, W - 2 * m, 640, range(64, 132, 2), ratio=1.22)
    block_h = tlh * len(lines)
    y = CARD_Y + (CH - block_h) / 2 - 20
    asc = tf.getmetrics()[0]
    for ln in _safe_title(item["title"]).split("\n"):
        lw = d.textlength(ln, font=tf)
        mk = _marker(int(lw + 26), int(asc * 0.60), accent)
        base.paste(mk, (int(x - 12), int(y + asc * 0.24)), mk)     # 형광펜은 배경에
        td.text((x, y), ln, font=tf, fill=fg)                      # 글자는 왜곡 레이어에
        y += tlh

    hint = "→  넘겨서 보기"
    hf = _font(Fb, 32)
    d.text(((W - d.textlength(hint, font=hf)) / 2, CARD_Y + CH - m - 78), hint,
           font=hf, fill=sub)
    hnf = _font(Fr, 24)
    handle = cfg.get("handle", "@your_handle")
    d.text((W - m - d.textlength(handle, font=hnf), CARD_Y + CH - m - 2), handle,
           font=hnf, fill=sub)
    _page_dots(d, cfg, 0)
    return np.asarray(base), np.asarray(title)


def _smooth_noise(gh: int, gw: int, rng) -> np.ndarray:
    """저해상 랜덤을 부드럽게 확대해 -1..1 변위 필드로."""
    g = rng.standard_normal((gh, gw)).astype(np.float32)
    im = Image.fromarray(((g - g.min()) / (np.ptp(g) + 1e-6) * 255).astype(np.uint8))
    a = np.asarray(im.resize((W, H), Image.BICUBIC), dtype=np.float32) / 255.0
    return a * 2.0 - 1.0


def _render_cover_frames(bg: np.ndarray, title: np.ndarray, out_dir: Path, n: int) -> None:
    """제목 레이어에 작고 불규칙한 지글거림(boil) 을 줘서 프레임 저장."""
    rng = np.random.default_rng(7)
    K = 6
    dxs = [_smooth_noise(22, 40, rng) for _ in range(K)]
    dys = [_smooth_noise(22, 40, rng) for _ in range(K)]
    ys, xs = np.mgrid[0:H, 0:W]
    bgf = bg.astype(np.float32)
    for f in range(n):
        pos = f / JITTER_HOLD
        i = int(pos) % K
        u = pos - int(pos)
        u = u * u * (3 - 2 * u)                       # smoothstep
        dx = (dxs[i] * (1 - u) + dxs[(i + 1) % K] * u) * JITTER_AMP
        dy = (dys[i] * (1 - u) + dys[(i + 1) % K] * u) * JITTER_AMP
        sy = np.clip((ys + dy).round().astype(np.int32), 0, H - 1)
        sx = np.clip((xs + dx).round().astype(np.int32), 0, W - 1)
        warped = title[sy, sx]
        a = warped[:, :, 3:4].astype(np.float32) / 255.0
        frame = bgf * (1 - a) + warped[:, :, :3].astype(np.float32) * a
        Image.fromarray(frame.astype(np.uint8)).save(out_dir / f"cov_{f:04d}.png")


def _content_frame(content_jpg: Path, cfg: dict, out_dir: Path) -> Path:
    base, d = _tall_bg(cfg)
    base.paste(Image.open(content_jpg).convert("RGB"), (0, CARD_Y))
    _page_dots(d, cfg, 1)
    p = out_dir / "content.png"
    base.save(p)
    return p


def render_reel(item: dict, out_dir: Path, cfg: dict | None = None) -> Path:
    cfg = cfg or load_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    frm = out_dir / "_frames"
    frm.mkdir(exist_ok=True)

    existing = sorted(out_dir.glob("[0-9].jpg"), key=lambda p: int(p.stem))
    cards = existing if existing else render_item(item, out_dir / "_cards", cfg)

    n_cov = int(COVER_SEC * FPS)
    bg, title = _cover_layers(item, cfg)
    _render_cover_frames(bg, title, frm, n_cov)
    content_png = _content_frame(cards[1], cfg, frm)

    mp4 = out_dir / "reel.mp4"
    ff = _ffmpeg()
    n_con = int(CONTENT_SEC * FPS)
    dur = COVER_SEC + CONTENT_SEC - XFADE
    offset = n_cov / FPS - XFADE

    # 커버: 물결 프레임 시퀀스 / 내용: 정지 + 느린 줌. 둘 다 CFR 고정.
    vf = (
        f"[0:v]fps={FPS},settb=1/{FPS},format=yuv420p[cov];"
        f"[1:v]scale=1188:2100,"
        f"zoompan=z='min(zoom+0.0006,1.05)':d={n_con}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
        f"fps={FPS},settb=1/{FPS},format=yuv420p[con];"
        f"[cov][con]xfade=transition=slideleft:duration={XFADE}:offset={offset:.2f}[v]"
    )
    cmd = [ff, "-y",
           "-framerate", str(FPS), "-i", str(frm / "cov_%04d.png"),
           "-loop", "1", "-i", str(content_png)]

    audio = cfg.get("reel_audio", "")
    apath = (ROOT / audio) if audio else None
    if apath and apath.exists():
        cmd += ["-stream_loop", "-1", "-i", str(apath)]
        amap = ["-map", "2:a", "-af",
                f"afade=t=in:d=0.6,afade=t=out:st={dur - 1:.1f}:d=1,volume=0.55"]
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
