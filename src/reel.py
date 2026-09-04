"""항목 1개를 릴스용 세로 영상(mp4)으로 만든다.

- 커버 카드 -> 슬라이드업 전환 -> 내용 카드. 약 11초.
- 9:16 (1080x1920). 카드(4:5)를 종이색 캔버스 중앙에 얹음.
- 오디오: settings 의 reel_audio(mp3 경로) 있으면 사용, 없으면 무음.
  (무음으로 올린 뒤 인스타 앱에서 트렌딩 오디오를 붙이는 걸 권장)

ffmpeg 는 imageio-ffmpeg 가 번들한 바이너리를 사용 (시스템 설치 불필요).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .common import ROOT, load_settings
from .render import _blend, _dot_grid, render_item

W, H = 1080, 1920
COVER_SEC = 4.0
CONTENT_SEC = 8.0
XFADE = 0.6


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _frame(card: Image.Image, cfg: dict, idx: int, total: int) -> Image.Image:
    """1080x1350 카드를 1080x1920 종이 캔버스 중앙에 배치."""
    th = cfg["tracks"]["A"]
    bg, sub, accent = th["bg"], th.get("sub", "#8A7A5C"), th["accent"]
    canvas = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(canvas)
    _dot_grid(d, W, H, _blend(sub, bg, 0.16))
    cw, ch = card.size
    x, y = (W - cw) // 2, (H - ch) // 2
    canvas.paste(card, (x, y))
    # 하단 페이지 도트
    n = total
    gap = 26
    tot_w = n * 14 + (n - 1) * gap
    sx = (W - tot_w) // 2
    for i in range(n):
        c = accent if i == idx else _blend(sub, bg, 0.5)
        d.ellipse([sx + i * (14 + gap), H - 90, sx + i * (14 + gap) + 14, H - 76], fill=c)
    return canvas


def render_reel(item: dict, out_dir: Path, cfg: dict | None = None) -> Path:
    cfg = cfg or load_settings()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 캐러셀 단계에서 이미 렌더된 카드(1.jpg, 2.jpg...)를 재사용, 없으면 새로 렌더
    existing = sorted(out_dir.glob("[0-9].jpg"), key=lambda p: int(p.stem))
    card_paths = existing if existing else render_item(item, out_dir / "_cards", cfg)
    frames = []
    for i, p in enumerate(card_paths):
        fr = _frame(Image.open(p).convert("RGB"), cfg, i, len(card_paths))
        fp = out_dir / f"_frame{i + 1}.png"
        fr.save(fp)
        frames.append(fp)

    # 지금 콘텐츠는 항상 커버 + 내용 2장. (3장 이상이면 첫 전환만 적용)
    cover, content = frames[0], frames[1]
    mp4 = out_dir / "reel.mp4"
    ff = _ffmpeg()

    audio = cfg.get("reel_audio", "")
    apath = (ROOT / audio) if audio else None
    dur = COVER_SEC + CONTENT_SEC - XFADE

    vf = (f"[0:v]fps=30,format=yuv420p[a];[1:v]fps=30,format=yuv420p[b];"
          f"[a][b]xfade=transition=slideup:duration={XFADE}:offset={COVER_SEC - XFADE}[v]")

    cmd = [ff, "-y",
           "-loop", "1", "-t", str(COVER_SEC), "-i", str(cover),
           "-loop", "1", "-t", str(CONTENT_SEC), "-i", str(content)]
    if apath and apath.exists():
        cmd += ["-stream_loop", "-1", "-i", str(apath)]
        amap = ["-map", "2:a",
                "-af", f"afade=t=in:d=0.6,afade=t=out:st={dur - 1:.1f}:d=1,volume=0.55"]
    else:
        cmd += ["-f", "lavfi", "-t", str(dur + 1), "-i", "anullsrc=r=44100:cl=stereo"]
        amap = ["-map", "2:a"]

    cmd += ["-filter_complex", vf, "-map", "[v]", *amap,
            "-t", f"{dur:.2f}", "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart", "-shortest", str(mp4)]

    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not mp4.exists():
        raise RuntimeError("ffmpeg 실패:\n" + (r.stderr or "")[-2000:])

    for f in frames:
        f.unlink(missing_ok=True)
    return mp4


if __name__ == "__main__":
    import sys
    from .common import OUTPUT_DIR, load_all_items
    slug = sys.argv[1] if len(sys.argv) > 1 else load_all_items()[0]["slug"]
    it = next(x for x in load_all_items() if x["slug"] == slug)
    p = render_reel(it, OUTPUT_DIR / "preview" / f"{slug}_reel")
    print("ok ->", p, p.stat().st_size, "bytes")
