"""Pixabay 사진으로 만드는 세로 릴스(정보 몇 컷 + 반전).

  0초부터 훅 문구 -> 컷 3개(사진 + 큰 자막, 컷마다 줌) -> 반전 한 줄 + 공유 유도.
  사진은 Pixabay API(PIXABAY_API_KEY)로 검색해 내려받는다(캐시: output/_stock_cache).

사용: python -m src.reel_stock <slug> [track_index]
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance

from .common import OUTPUT_DIR, ROOT, load_dotenv, load_settings
from .reel_search import _ffmpeg
from .render import _font, _rgb, _wrap

W, H, FPS = 1080, 1920, 30
HOOK_SEC, BEAT_SEC, REVEAL_SEC = 2.4, 2.8, 3.0
ACCENT = "#2F6FE4"       # 배지·진행바·버튼 (신뢰감 있는 블루)
HL = "#8EC5FF"           # 강조 글자색(어두운 사진 위 가독성)
TITLE_FONT = "DoHyeon-Regular.ttf"
CACHE = OUTPUT_DIR / "_stock_cache"
API = "https://pixabay.com/api/"
TTS_CACHE = OUTPUT_DIR / "_tts_cache"
PAD_SEC = 0.35
SHORT_CHARS = 12   # 공백 뺀 글자 수가 이 이하면 자막 1줄 고정, 초과면 2줄 허용
MIN_MATCH = 0.97   # 음성인식 일치도 기준. 낮으면 발음이 뭉개진 것이므로 시드를 바꿔 다시 뽑는다
MAX_SEC = 30.0   # 릴스 길이 상한. 핵심만 담아 이 안에 끝내야 한다


_D = "영일이삼사오육칠팔구"


def _sino(n: int) -> str:
    """정수를 한자어 수(천팔백팔십구 등)로. 음성인식이 숫자로 적어도 대본과 비교하려고 쓴다."""
    if n == 0:
        return "영"
    out = ""
    for unit, name in ((1000, "천"), (100, "백"), (10, "십")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if q == 1 else _D[q]) + name
    if n:
        out += _D[n]
    return out


_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_UNITS = "살|번|명|마리|시간|분야"


def _native(n: int) -> str:
    """고유어 수(한, 두, 스물, 여든두 …). 살·번·명 같은 단위 앞에서 쓴다."""
    if n == 20:
        return "스무"
    return _TENS[n // 10] + _ONES[n % 10]


def _norm(t: str) -> str:
    t = re.sub(r"(?<=\d),(?=\d)", "", t)   # 1,093 -> 1093
    # 음성인식이 '여든두 살'을 '82살'로 적는 경우 등: 고유어 단위 앞 숫자는 고유어 수로, 나머지는 한자어 수로.
    t = re.sub(rf"(\d+)\s*(?={_NATIVE_UNITS})",
               lambda m: _native(int(m[1])) if int(m[1]) < 100 else m[0], t)
    t = re.sub(r"\d+", lambda m: _sino(int(m[0])), t)
    return re.sub(r"[^가-힣]", "", t)


def _stt(path: Path) -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    with open(path, "rb") as f:
        r = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
                          headers={"xi-api-key": key},
                          data={"model_id": "scribe_v1", "language_code": "kor"},
                          files={"file": f}, timeout=180)
    if not r.ok:
        raise RuntimeError(f"ElevenLabs STT 실패 {r.status_code}: {r.text[:200]}")
    return r.json().get("text", "")


def _tts(text: str, cfg: dict, tries: int = 8) -> Path:
    """ElevenLabs TTS. 생성한 음성을 음성인식으로 다시 들어보고, 대본과 다르게 읽히면
    (숫자 발음 뭉개짐 등) 시드를 바꿔 다시 뽑는다. 검증 통과한 것만 캐시한다."""
    load_dotenv()
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY 가 없습니다.")
    t = cfg.get("tts", {})
    voice, model = t["voice_id"], t.get("model", "eleven_multilingual_v2")
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    path = TTS_CACHE / (hashlib.sha1(f"{voice}|{model}|{text}".encode("utf-8")).hexdigest()[:16] + ".mp3")
    if path.exists():
        return path
    want, best = _norm(text), 0.0
    for n in range(tries):
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            params={"output_format": "mp3_44100_128"},
            json={"text": text, "model_id": model, "language_code": "ko", "seed": 1000 + n,
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8,
                                     "style": 0.25, "speed": 1.08}},
            timeout=90)
        if not r.ok:
            raise RuntimeError(f"ElevenLabs 실패 {r.status_code}: {r.text[:200]}")
        tmp = path.with_suffix(".try.mp3")
        tmp.write_bytes(r.content)
        heard = _stt(tmp)
        ratio = difflib.SequenceMatcher(None, want, _norm(heard)).ratio()
        best = max(best, ratio)
        print(f"  [음성검수 {n + 1}/{tries}] 일치도 {ratio:.2f} | {heard}")
        if ratio >= MIN_MATCH:
            tmp.replace(path)
            return path
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"음성 검수 실패(최고 일치도 {best:.2f}): {text}")


def _mp3_dur(path: Path) -> float:
    out = subprocess.run([_ffmpeg(), "-i", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def _get(url: str, **kw) -> requests.Response:
    """Pixabay 는 요청이 몰리면 429 를 준다. 대기 후 재시도."""
    for n in range(6):
        r = requests.get(url, timeout=60, **kw)
        if r.status_code != 429:
            r.raise_for_status()
            return r
        time.sleep(15 * (n + 1))
    r.raise_for_status()
    return r


def _search(query: str, used: set[int], img_id: int | None = None) -> Image.Image:
    load_dotenv()
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PIXABAY_API_KEY 가 없습니다.")
    CACHE.mkdir(parents=True, exist_ok=True)
    if img_id:
        r = _get(API, params={"key": key, "id": img_id})
    else:
      r = _get(API, params={
        "key": key, "q": query, "image_type": "photo", "orientation": "vertical",
        "min_height": 1200, "safesearch": "true", "order": "popular", "per_page": 20,
      })
    hits = [h for h in r.json().get("hits", []) if img_id or h["id"] not in used]
    if not hits:
        raise RuntimeError(f"Pixabay 검색 결과 없음: {query}")
    h = hits[0]
    used.add(h["id"])
    path = CACHE / f"{h['id']}.jpg"
    if not path.exists():
        path.write_bytes(_get(h["largeImageURL"]).content)
    return Image.open(path).convert("RGB")


def _prep(img: Image.Image) -> Image.Image:
    """화면을 꽉 채우도록 크롭 + 약간 어둡게(자막 가독성). 줌 여유 1.18배."""
    s = 1.18
    tw, th = int(W * s), int(H * s)
    sc = max(tw / img.width, th / img.height)
    img = img.resize((int(img.width * sc) + 1, int(img.height * sc) + 1), Image.LANCZOS)
    x, y = (img.width - tw) // 2, (img.height - th) // 2
    img = img.crop((x, y, x + tw, y + th))
    return ImageEnhance.Brightness(img).enhance(0.62)


def _gradient() -> Image.Image:
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = g.load()
    for y in range(H):
        a = 0
        if y < 420:
            a = int(150 * (1 - y / 420))
        elif y > 1000:
            a = int(190 * min(1.0, (y - 1000) / 600))
        for x in range(W):
            px[x, y] = (0, 0, 0, a)
    return g


def _segments(line: str, hl: str | None) -> list[tuple[str, bool]]:
    if hl and hl in line:
        i = line.index(hl)
        return [(line[:i], False), (hl, True), (line[i + len(hl):], False)]
    return [(line, False)]


def _draw_text(layer: Image.Image, raw: str, size: int, cy: float, alpha: float, lift: int):
    """'**강조**' 표기 지원. 줄바꿈은 \\n 으로 직접 지정."""
    d = ImageDraw.Draw(layer)
    lines = raw.split("\n")
    joined = " ".join(lines)
    plain = joined.replace("**", "")
    max_w = W - 100
    if len(plain.replace(" ", "")) <= SHORT_CHARS:
        # 글자 수가 적으면 무조건 1줄(필요하면 글자를 줄여서라도)
        lines = [joined]
        while size > 60 and d.textlength(plain, font=_font(TITLE_FONT, size)) > max_w:
            size -= 2
    else:
        # 글자 수가 많으면 지정한 줄바꿈(2줄)을 유지하고, 넘치면 글자만 줄임
        while size > 60 and max(d.textlength(l.replace("**", ""), font=_font(TITLE_FONT, size))
                                for l in lines) > max_w:
            size -= 2
    font = _font(TITLE_FONT, size)
    lh = int(size * 1.28)
    top = cy - lh * len(lines) / 2 + lift
    a = int(255 * alpha)
    for n, line in enumerate(lines):
        hl = None
        if "**" in line:
            pre, rest = line.split("**", 1)
            hl, post = rest.split("**", 1)
            line = pre + hl + post
        segs = _segments(line, hl)
        total = sum(d.textlength(t, font=font) for t, _ in segs)
        x = (W - total) / 2
        y = top + n * lh
        for t, is_hl in segs:
            if t:
                d.text((x, y), t, font=font, fill=(*_rgb(HL if is_hl else "#FFFFFF"), a),
                       stroke_width=9, stroke_fill=(0, 0, 0, int(230 * alpha)))
                x += d.textlength(t, font=font)


def render_stock_reel(item: dict, out_dir: Path, cfg: dict | None = None,
                      track_index: int | None = None) -> Path:
    cfg = cfg or load_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    used: set[int] = set()

    raw = [(item["hook"], item["hook_query"], HOOK_SEC, 120, 880, item.get("hook_say"), item.get("hook_img"))]
    for b in item["beats"]:
        raw.append((b["text"], b["query"], BEAT_SEC, 98, 1120, b.get("say"), b.get("img")))
    raw.append((item["reveal"], item["reveal_query"], REVEAL_SEC, 104, 1000, item.get("reveal_say"), item.get("reveal_img")))
    scenes, voices = [], []
    ids = []
    for text, q, sec, size, ty, say, iid in raw:
        ids.append(iid)
        vp = _tts(say, cfg) if say else None
        if vp:
            sec = max(sec, _mp3_dur(vp) + PAD_SEC)
        scenes.append((text, q, sec, size, ty))
        voices.append(vp)
    imgs = [_prep(_search(s[1], used, i)) for s, i in zip(scenes, ids)]
    if sum(s[2] for s in scenes) > MAX_SEC:
        raise RuntimeError(f"릴스가 {sum(s[2] for s in scenes):.1f}초로 상한 {MAX_SEC:.0f}초를 넘음: 대사를 줄이세요")
    total = sum(round(s[2] * FPS) for s in scenes)

    grad = _gradient()
    badge_font = _font(TITLE_FONT, 46)
    cta_font = _font(TITLE_FONT, 50)
    cta = item.get("cta", "")

    mp4 = out_dir / "reel_stock.mp4"
    ff = _ffmpeg()
    dur = total / FPS
    audio_cfg = cfg.get("reel_audio", "")
    tracks = [t for t in (audio_cfg if isinstance(audio_cfg, list) else [audio_cfg]) if t]
    apath = (ROOT / tracks[(track_index or 0) % len(tracks)]) if tracks else None
    cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-framerate", str(FPS), "-i", "-"]
    starts, acc0 = [], 0.0
    for sc in scenes:
        starts.append(acc0)
        acc0 += sc[2]
    if apath and apath.exists():
        cmd += ["-stream_loop", "-1", "-i", str(apath)]
    else:
        cmd += ["-f", "lavfi", "-t", str(dur + 1), "-i", "anullsrc=r=44100:cl=stereo"]
    vlist = [(v, st) for v, st in zip(voices, starts) if v]
    for v, _ in vlist:
        cmd += ["-i", str(v)]
    fade = f"afade=t=in:d=0.4,afade=t=out:st={max(0.0, dur - 0.8):.2f}:d=0.8"
    if vlist:
        parts = [f"[1:a]{fade},volume=0.16[bg]"]
        for i, (_, st) in enumerate(vlist):
            ms = int(st * 1000)
            parts.append(f"[{i + 2}:a]adelay={ms}|{ms},volume=1.6[v{i}]")
        labels = "".join(f"[v{i}]" for i in range(len(vlist)))
        parts.append(f"{labels}amix=inputs={len(vlist)}:normalize=0:dropout_transition=0[vo]")
        parts.append("[bg][vo]amix=inputs=2:normalize=0:dropout_transition=0[aout]")
        cmd += ["-filter_complex", ";".join(parts)]
        amap = ["-map", "[aout]"]
    else:
        cmd += ["-af", fade + ",volume=0.5"]
        amap = ["-map", "1:a"]
    cmd += ["-map", "0:v", "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-level", "4.0", *amap, "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart", "-shortest", str(mp4)]
    errf = open(out_dir / "_ffmpeg.log", "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errf)

    bounds, acc = [], 0
    for s in scenes:
        acc += round(s[2] * FPS)
        bounds.append(acc)

    for f in range(total):
        si = next(i for i, b in enumerate(bounds) if f < b)
        start = bounds[si - 1] if si else 0
        n = bounds[si] - start
        t = (f - start) / max(1, n - 1)
        zoom = 1.0 + 0.16 * t if si % 2 == 0 else 1.16 - 0.16 * t
        base = imgs[si]
        cw, ch = base.width / zoom, base.height / zoom
        cx, cy = base.width / 2, base.height / 2
        frame = base.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2)))
        frame = frame.resize((W, H), Image.BILINEAR).convert("RGBA")
        frame.alpha_composite(grad)

        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        text, _, _, size, ty = scenes[si]
        p = min(1.0, (f - start) / 7)
        p = p * p * (3 - 2 * p)
        if si == 0:
            p = 1.0
        _draw_text(layer, text, size, ty, p, int(26 * (1 - p)))

        d = ImageDraw.Draw(layer)
        d.text((60, 186), "오늘의 TMI", font=badge_font, fill=(255, 255, 255, 255),
               stroke_width=5, stroke_fill=(0, 0, 0, 200))
        d.rounded_rectangle([60, 150, W - 60, 158], radius=4, fill=(255, 255, 255, 70))
        d.rounded_rectangle([60, 150, 60 + int((W - 120) * (f + 1) / total), 158], radius=4,
                            fill=(*_rgb(ACCENT), 255))
        if si == len(scenes) - 1 and cta:
            cp = min(1.0, (f - start) / 9)
            tw = d.textlength(cta, font=cta_font)
            yy = 1370 + int(20 * (1 - cp))
            d.text(((W - tw) / 2, yy), cta, font=cta_font, fill=(255, 255, 255, int(255 * cp)),
                   stroke_width=7, stroke_fill=(0, 0, 0, int(220 * cp)))
        frame.alpha_composite(layer)
        proc.stdin.write(frame.convert("RGB").tobytes())

    proc.stdin.close()
    rc = proc.wait()
    errf.close()
    if rc != 0 or not mp4.exists():
        err = (out_dir / "_ffmpeg.log").read_text(encoding="utf-8", errors="replace")
        raise RuntimeError("ffmpeg 실패:\n" + err[-2000:])
    return mp4


def qa(mp4: Path) -> Path:
    """검수용: 길이/음량 출력 + 영상을 6등분한 지점의 프레임 시트를 만든다."""
    ff = _ffmpeg()
    info = subprocess.run([ff, "-i", str(mp4)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    vol = subprocess.run([ff, "-i", str(mp4), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    print(f"길이 {dur:.1f}s (상한 {MAX_SEC:.0f}s) |",
          " | ".join(re.findall(r"(mean_volume: \S+ dB|max_volume: \S+ dB)", vol)))
    fr = []
    for i in range(6):
        f = mp4.parent / f"_qa_{i}.png"
        subprocess.run([ff, "-y", "-ss", f"{dur * (i + 0.5) / 6:.2f}", "-i", str(mp4), "-frames:v", "1",
                        "-vf", "scale=360:-1", str(f)], capture_output=True)
        fr.append(f)
    sheet = mp4.parent / "_qa.png"
    subprocess.run([ff, "-y"] + [x for f in fr for x in ("-i", str(f))]
                   + ["-filter_complex", f"hstack={len(fr)}", str(sheet)], capture_output=True)
    for f in fr:
        f.unlink(missing_ok=True)
    return sheet


if __name__ == "__main__":
    slug = sys.argv[1]
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else None
    items = []
    for fn in ("bank_people.json", "stock_sample.json"):
        items += json.loads((ROOT / "content" / fn).read_text(encoding="utf-8"))
    it = next(x for x in items if x["slug"] == slug)
    p = render_stock_reel(it, OUTPUT_DIR / "preview" / ("_stock_" + slug), track_index=idx)
    print("ok ->", p, p.stat().st_size, "bytes")
    print("qa ->", qa(p))
