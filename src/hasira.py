# src/hasira.py
# HASIRA_yo! 제작 라인 — 넌버벌 음악 롱폼 (16:9 · 30분~2시간)
#
# 흐름
#   ① 기획   : 키워드 하나 → Claude 가 제목·그림 프롬프트·움직임 프롬프트·곡 목록(JSON)
#   ② 그림   : Replicate flux-dev 16:9 한 장 (또는 직접 올린 그림)
#   ③ 움직임 : MiniMax 6초 클립 → 앞으로+거꾸로 이어 붙여 끊김 없는 루프 (또는 정지 그림)
#   ④ 음악   : ElevenLabs Music / Google Lyria 3.5 / 직접 올린 곡(Suno 등)
#   ⑤ 합성   : 곡마다 음량 맞춤 → 크로스페이드 연결 → 루프 영상을 스트림 복사로 반복 → 1시간 MP4
#   ⑥ 전달   : Cloudflare R2 에 올리고 7일짜리 내려받기 링크
#   ⑦ 업로드 : 일본어 제목·설명 + 곡 목록 타임스탬프(유튜브 챕터)
#
# 오래 걸리는 ③④⑤ 는 백그라운드 스레드에서 돈다(화면이 다시 실행돼도 끊기지 않음).
# 이 모듈 안에서는 st.* 를 호출하지 않는다.
#
# 확인한 사양
#   - ElevenLabs music.compose(prompt, music_length_ms, force_instrumental) → Iterator[bytes] (MP3)
#     엔진 배경음악에서 이미 쓰는 호출 · API 요금 분당 $0.15 (elevenlabs.io/pricing/api)
#   - Lyria 3.5 : client.interactions.create(model="lyria-3.5", input=...) → output_audio.data (base64 MP3)
#     곡당 약 2분, 연주곡은 프롬프트로 지정 (ai.google.dev/gemini-api/docs/music-generation)
#   - 유튜브 챕터 : 첫 줄 00:00, 3개 이상, 오름차순, 각 10초 이상 (support.google.com/youtube/answer/9884579)

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time

# ── 설정 ──────────────────────────────────────────────────────────────────────
W, H, FPS = 1920, 1080, 25
XFADE_SEC = 4.0                  # 곡 사이 크로스페이드
FADE_IN_SEC, FADE_OUT_SEC = 2.0, 6.0
LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"
EL_PRICE_PER_MIN = 0.15          # ElevenLabs Music API (분당, 2026-10 확인)
LYRIA_MODEL = "lyria-3.5"

PROVIDERS = {
    "elevenlabs": "ElevenLabs Music (바로 사용 가능 · 분당 $0.15)",
    "lyria":      "Google Lyria 3.5 (연결 테스트 통과 후 사용)",
    "upload":     "직접 올린 곡 (Suno 등에서 만든 MP3)",
}
LENGTH_OPTIONS = {30: "30분", 60: "1시간", 90: "1시간 30분", 120: "2시간"}
VISUAL_MODES = {"motion": "움직이는 그림 (MiniMax 6초 → 끊김 없는 반복)", "still": "정지 그림 (비용 없음)"}

PLAN_SYSTEM = """당신은 일본 시청자를 위한 유튜브 음악 채널 'HASIRA_yo!'의 아트 디렉터 겸 음악 프로듀서입니다.
채널 형식: 말 없는 연주곡을 1시간 이상 이어 틀고, 화면에는 16:9 그림 한 장과 반복되는 작은 움직임만 나옵니다.
작업·공부·휴식·잠들기 전에 틀어 두는 배경 음악입니다. 채널 톤: 따뜻하고 차분함, 로즈골드와 짙은 갈색의 색감.

키워드를 받아 아래 JSON 하나만 출력하세요. 설명 문장이나 ``` 표시는 쓰지 않습니다.

{
  "title_ja": "유튜브 제목 (일본어, 40자 안팎, 용도+분위기+장르, 예: 雨の夜カフェで聴くジャズピアノ | 作業用・勉強用BGM)",
  "title_ko": "같은 제목의 한국어 뜻",
  "concept_ko": "이 편의 장면과 음악을 한 문장으로 (한국어)",
  "image_prompt": "영문. 16:9 가로 그림 한 장. 장소·시간·빛·주요 사물·화풍을 확정적으로 적는다",
  "motion_prompt": "영문. 그림 속에서 계속 반복되는 작은 움직임 하나 또는 둘",
  "music_style": "영문. 모든 곡에 공통인 장르·악기 편성·템포(BPM)·분위기",
  "tracks": [
    {"title_ja": "곡 제목(일본어, 짧게)", "title_en": "Track title in English", "prompt": "영문. 이 곡만의 변화(조성·주 악기·템포 차이·분위기)"}
  ]
}

규칙
- tracks 는 요청한 개수와 정확히 같게 만듭니다. 곡끼리 같은 장르 안에서 서로 다르게 들리도록 주 악기·조성·템포를 바꿉니다.
- 모든 곡은 가사·목소리 없는 연주곡입니다. 실존 아티스트 이름·곡 이름은 쓰지 않습니다.
- image_prompt: 사진 한 장을 묘사하듯 한 가지 상태·한 가지 장면만 확정적으로 씁니다. "or", "maybe", "slightly", "could", "appears" 같은 선택지·추측·완곡 표현을 쓰지 않습니다.
  글자·간판 문자·로고·워터마크가 없다고 명시합니다(no text, no letters, no logo). 사람이 나오면 뒷모습이나 멀리 있는 작은 실루엣만 둡니다.
- motion_prompt: 카메라는 고정(static locked-off camera, no camera movement, no zoom, no cuts)이고,
  비·눈·꽃잎·김·촛불·물결·커튼처럼 반복되는 작은 움직임만 적습니다. 사람·사물이 화면 밖으로 나가거나 새로 들어오지 않습니다.
"""

PACK_SYSTEM = """당신은 일본 시청자를 위한 유튜브 음악 채널 'HASIRA_yo!'의 업로드 담당자입니다.
말 없는 연주곡을 1시간 이상 이어 튼 영상의 업로드 정보를 일본어로 씁니다. 아래 JSON 하나만 출력하세요.

{
  "title": "제목 (일본어, 70자 이내, 용도+분위기+장르+길이, 예: 【1時間】雨の夜カフェで聴くジャズピアノ | 作業用・勉強用BGM)",
  "description": "설명 첫 부분 (일본어 3~6줄: 장면 소개, 어울리는 용도, 채널 구독 안내 한 줄). 곡 목록은 쓰지 않습니다.",
  "tags": ["일본어·영어 검색어 15개 안팎"],
  "hashtags": ["#作業用BGM 처럼 # 붙인 3개"]
}
과장된 효능(집중력 몇 배, 치료 효과 등)은 쓰지 않습니다."""

UPLOAD_SETTINGS = [
    ("카테고리", "음악"),
    ("아동용 여부", "아니요, 아동용이 아닙니다"),
    ("동영상 언어", "언어 없음 (또는 일본어)"),
    ("챕터", "설명란 곡 목록 타임스탬프로 자동 생성 (첫 줄 00:00)"),
    ("섬네일", "16:9 1280×720 — 아래 그림 파일을 바탕으로 직접 제작"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def project_files(state: dict, *parts) -> str:
    d = os.path.join(state.get("project_dir", "projects/tmp"), "hasira", *parts[:-1])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, parts[-1])


def usable(path: str) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
                           capture_output=True, timeout=60)
        return float(json.loads(r.stdout.decode())["format"]["duration"])
    except Exception:
        return 0.0


def fmt_time(sec: float, force_hours: bool = False) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h or force_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _r2_ok(keys: dict) -> bool:
    from src import r2_store
    return r2_store.is_configured(keys)


def r2_key(state: dict, name: str) -> str:
    return f"hasira/{state.get('project_id', 'tmp')}/{name}"


def keep_in_r2(keys: dict, state: dict, local: str, name: str, content_type: str = "") -> str:
    """R2 가 설정돼 있으면 올리고 key 를 돌려준다. 실패·미설정이면 빈 문자열."""
    if not _r2_ok(keys) or not usable(local):
        return ""
    from src import r2_store
    try:
        return r2_store.upload_file(keys, local, r2_key(state, name), content_type)
    except Exception as e:
        print(f"[hasira] R2 업로드 실패 {name}: {e}", flush=True)
        return ""


def ensure_local(keys: dict, item: dict, dest: str) -> str:
    """item['local'] 이 없으면(서버 재시작·JSON 복구) R2 에서 다시 받아 온다."""
    if usable(item.get("local", "")):
        return item["local"]
    if item.get("r2_key") and _r2_ok(keys):
        from src import r2_store
        try:
            r2_store.download_file(keys, item["r2_key"], dest)
            if usable(dest):
                item["local"] = dest
                return dest
        except Exception as e:
            print(f"[hasira] R2 다시 받기 실패 {item.get('r2_key')}: {e}", flush=True)
    return ""


def _download(url: str, dest: str) -> str:
    import requests
    r = requests.get(url, stream=True, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    if not usable(dest):
        raise RuntimeError("내려받은 파일이 비어 있습니다.")
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# ① 기획
# ─────────────────────────────────────────────────────────────────────────────
def default_track_count(target_min: int, track_min: float) -> int:
    return max(3, int(round(target_min / max(track_min, 1.0))))


def make_plan(api_key: str, keyword: str, n_tracks: int, target_min: int) -> dict:
    import anthropic
    from src.prompts import SCRIPT_MODEL, _text_of, _extract_json
    client = anthropic.Anthropic(api_key=api_key)
    user = (f"키워드: {keyword.strip()}\n영상 길이: 약 {target_min}분\n"
            f"곡 개수: 정확히 {n_tracks}곡\nJSON 만 출력하세요.")
    last = None
    for _ in range(2):
        resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=8000, system=PLAN_SYSTEM,
                                      messages=[{"role": "user", "content": user}])
        try:
            plan = _extract_json(_text_of(resp))
            tracks = [t for t in (plan.get("tracks") or []) if isinstance(t, dict) and t.get("prompt")]
            if not plan.get("image_prompt") or not tracks:
                raise ValueError("image_prompt 또는 tracks 가 비어 있습니다.")
            plan["tracks"] = tracks[:n_tracks]
            return plan
        except Exception as e:
            last = e
    raise ValueError(f"기획 JSON 을 읽지 못했습니다: {last}")


def new_tracks_from_plan(plan: dict) -> list:
    return [{"no": i + 1, "title_ja": t.get("title_ja", ""), "title_en": t.get("title_en", ""),
             "prompt": t.get("prompt", ""), "status": "pending", "local": "", "r2_key": "",
             "seconds": 0.0, "source": "", "error": ""}
            for i, t in enumerate(plan.get("tracks") or [])]


def track_prompt(state: dict, track: dict, seconds: int) -> str:
    style = (state.get("plan") or {}).get("music_style", "")
    mins = max(1, round(seconds / 60))
    return (f"{style.rstrip(' .')}. {track.get('prompt', '').rstrip(' .')}. "
            f"Instrumental only, no vocals, no voice. About {mins} minutes long, "
            f"gentle intro and a soft natural ending.")


# ─────────────────────────────────────────────────────────────────────────────
# ② 그림 (16:9)
# ─────────────────────────────────────────────────────────────────────────────
def generate_image(replicate_token: str, prompt: str) -> str:
    """Replicate flux-dev 16:9 → URL (1시간 뒤 삭제되므로 바로 내려받아 보관할 것)."""
    from src import image_replicate as ir
    os.environ["REPLICATE_API_TOKEN"] = replicate_token
    inputs = {"prompt": prompt, "aspect_ratio": "16:9", "num_inference_steps": 28, "guidance": 3.5,
              "output_format": "jpg", "output_quality": 95, "num_outputs": 1}
    return ir._to_url(ir._run_prediction(ir.FLUX_DEV_MODEL, inputs, ir.TIMEOUT_DEV, "[hasira/flux-dev 16:9]"))


def save_image(keys: dict, state: dict, src: str, source: str) -> dict:
    """URL 또는 로컬 파일을 프로젝트에 보관하고 1280×720 섬네일 바탕도 만든다."""
    ext = ".png" if src.lower().split("?")[0].endswith(".png") else ".jpg"
    dest = project_files(state, f"image{ext}")
    if src.startswith("http"):
        _download(src, dest)
    elif os.path.abspath(src) != os.path.abspath(dest):
        shutil.copyfile(src, dest)
    thumb = project_files(state, "thumbnail_base_1280x720.jpg")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", dest, "-vf",
                    "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
                    "-q:v", "2", thumb], check=True, timeout=120)
    img = {"local": dest, "source": source, "thumb_local": thumb,
           "r2_key": keep_in_r2(keys, state, dest, f"image{ext}", "image/jpeg" if ext == ".jpg" else "image/png")}
    state["image"] = img
    state["loop"] = {}                     # 그림이 바뀌면 예전 루프는 무효
    state["final"] = {}
    return img


# ─────────────────────────────────────────────────────────────────────────────
# ③ 루프 영상
# ─────────────────────────────────────────────────────────────────────────────
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0"]
FILL = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"


def _frame_count(path: str) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path],
                       capture_output=True, timeout=120)
    try:
        return int(r.stdout.decode().strip().split(",")[0])
    except Exception:
        return 0


def build_pingpong_loop(raw_clip: str, out: str) -> str:
    """6초 클립 → 앞으로 재생 + 거꾸로 재생(양 끝 프레임 1장씩 제외) = 이음매 없는 약 12초 루프.
    거꾸로 재생은 원본 해상도에서 처리해 메모리를 아낀다(720p 150장 ≈ 200MB)."""
    n = _frame_count(raw_clip)
    rev_trim = f"trim=start_frame=1:end_frame={max(n - 1, 2)}," if n > 3 else ""
    vf = (f"[0:v]fps={FPS},split[f][b];[b]reverse,{rev_trim}setpts=PTS-STARTPTS[r];"
          f"[f][r]concat=n=2:v=1:a=0,{FILL},format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw_clip, "-filter_complex", vf, "-map", "[v]",
                    *X264, "-crf", "22", "-maxrate", "2M", "-bufsize", "4M", "-an",
                    "-movflags", "+faststart", out], check=True, timeout=900)
    return out


def build_still_loop(image: str, out: str, seconds: int = 10) -> str:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", str(seconds),
                    "-i", image, "-vf", f"{FILL},format=yuv420p", *X264, "-tune", "stillimage",
                    "-crf", "20", "-an", "-movflags", "+faststart", out], check=True, timeout=600)
    return out


def motion_prompt_full(state: dict) -> str:
    mp = (state.get("plan") or {}).get("motion_prompt", "").rstrip(" .")
    return (f"{mp}. Static locked-off camera, no camera movement, no zoom, no pan, no cuts, "
            f"the scene composition stays exactly the same, only the small repeating elements move, "
            f"no text.")


# ─────────────────────────────────────────────────────────────────────────────
# ④ 음악
# ─────────────────────────────────────────────────────────────────────────────
class StopAll(RuntimeError):
    """크레딧·권한 문제처럼 다음 곡도 똑같이 실패할 오류."""


def _gen_elevenlabs(api_key: str, prompt: str, seconds: int, dest: str) -> str:
    from elevenlabs import ElevenLabs
    try:
        audio = ElevenLabs(api_key=api_key).music.compose(
            prompt=prompt, music_length_ms=int(max(10, min(600, seconds)) * 1000), force_instrumental=True)
        with open(dest, "wb") as f:
            for c in audio:
                if c:
                    f.write(c)
    except Exception as e:
        msg = str(e)
        if any(k in msg.lower() for k in ("quota", "credit", "401", "402", "payment", "unauthorized")):
            raise StopAll(f"ElevenLabs 크레딧·권한 문제로 멈췄습니다: {msg[:300]}")
        raise
    if not usable(dest):
        raise RuntimeError("ElevenLabs 가 빈 음악을 돌려줬습니다.")
    return dest


def _gen_lyria(api_key: str, prompt: str, dest: str) -> str:
    from google import genai
    try:
        inter = genai.Client(api_key=api_key).interactions.create(model=LYRIA_MODEL, input=prompt)
    except Exception as e:
        msg = str(e)
        if any(k in msg for k in ("PERMISSION_DENIED", "SERVICE_DISABLED", "403", "RESOURCE_EXHAUSTED", "429",
                                  "API_KEY_INVALID", "billing")):
            raise StopAll(f"Google Lyria 연결 문제로 멈췄습니다: {msg[:300]}")
        raise
    audio = getattr(inter, "output_audio", None)
    raw = getattr(audio, "data", None) if audio is not None else None
    if not raw:
        raise RuntimeError("Lyria 응답에 output_audio 가 없습니다 (연결 테스트의 응답 구조 JSON 을 확인).")
    with open(dest, "wb") as f:
        f.write(base64.b64decode(raw) if isinstance(raw, str) else bytes(raw))
    return dest


def suno_style(state: dict, track: dict) -> str:
    """Suno 「Style of Music」 칸에 붙여 넣을 문장 (Instrumental 켜고 사용)."""
    style = (state.get("plan") or {}).get("music_style", "").rstrip(" .")
    return f"{style}. {track.get('prompt', '').rstrip(' .')}. Instrumental, no vocals."


def suno_sheet(state: dict) -> str:
    """기획 곡 목록 전체를 Suno 작업용 글 파일로."""
    plan = state.get("plan") or {}
    lines = [f"HASIRA_yo! — {plan.get('title_ja', state.get('title', ''))}",
             "Suno: Custom 모드 · Instrumental 켜기 · 아래 Title / Style 을 그대로 붙여 넣기", ""]
    for t in sorted(state.get("tracks", []), key=lambda x: x["no"]):
        if not t.get("prompt"):
            continue
        lines += [f"#{t['no']:02d}", f"Title: {t.get('title_en') or t.get('title_ja', '')}",
                  f"(곡 제목 표기: {t.get('title_ja', '')})", f"Style: {suno_style(state, t)}", ""]
    return "\n".join(lines)


def add_uploaded_track(keys: dict, state: dict, filename: str, data: bytes, no: int = None) -> dict:
    """직접 만든 곡(Suno 등) 넣기.
    no 를 주면 기획 목록의 그 자리에, 안 주면 아직 비어 있는 첫 자리에 넣는다(기획 제목 유지).
    빈 자리가 없으면 목록 끝에 추가하고 파일 이름(확장자 제외)을 곡 제목으로 쓴다."""
    tracks = state.setdefault("tracks", [])
    slot = None
    if no is not None:
        slot = next((t for t in tracks if t["no"] == no), None)
    else:
        slot = next((t for t in sorted(tracks, key=lambda x: x["no"])
                     if t.get("status") != "done" and t.get("prompt")), None)
    ext = os.path.splitext(filename)[1].lower() or ".mp3"
    tno = slot["no"] if slot else max([t["no"] for t in tracks] or [0]) + 1
    dest = project_files(state, "music", f"track_{tno:02d}{ext}")
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    sec = duration(tmp)
    if sec <= 0:
        os.remove(tmp)
        raise ValueError(f"{filename}: 오디오 파일로 읽을 수 없습니다.")
    os.replace(tmp, dest)
    fname = os.path.splitext(os.path.basename(filename))[0].strip()
    info = {"status": "done", "local": dest, "seconds": round(sec, 2), "source": "upload", "error": "",
            "file_name": os.path.basename(filename),
            "r2_key": keep_in_r2(keys, state, dest, f"music/track_{tno:02d}{ext}", "audio/mpeg")}
    if slot is None:
        slot = {"no": tno, "title_ja": fname, "title_en": fname, "prompt": ""}
        tracks.append(slot)
    slot.update(info)
    state["final"] = {}
    return slot


# ─────────────────────────────────────────────────────────────────────────────
# 백그라운드 작업
# ─────────────────────────────────────────────────────────────────────────────
_JOBS: dict = {}
_LOCK = threading.Lock()


def get_job(project_id: str):
    return _JOBS.get(project_id)


def is_running(project_id: str) -> bool:
    j = _JOBS.get(project_id)
    return bool(j and j["thread"].is_alive())


def request_stop(project_id: str) -> None:
    j = _JOBS.get(project_id)
    if j:
        j["stop"] = True


def _start(project_id: str, kind: str, label: str, target, args) -> bool:
    with _LOCK:
        if is_running(project_id):
            return False
        job = {"kind": kind, "label": label, "msg": "준비 중", "done": 0, "total": 0, "pct": 0.0,
               "error": "", "stop": False, "started_at": time.time(), "finished_at": None, "result": ""}
        th = threading.Thread(target=_wrap, args=(job, target, args), daemon=True)
        job["thread"] = th
        _JOBS[project_id] = job
        th.start()
        return True


def _wrap(job, target, args):
    try:
        target(job, *args)
    except BaseException as e:
        job["error"] = f"{type(e).__name__}: {e}"
        print(f"[hasira] {job['kind']} 작업 오류: {e}", flush=True)
    finally:
        job["finished_at"] = time.time()


def _save(save_fn, state):
    try:
        save_fn(state)
    except Exception as e:
        print(f"[hasira] 상태 저장 실패: {e}", flush=True)


# ── ③ 루프 작업 ──
def start_loop_job(state: dict, keys: dict, save_fn) -> bool:
    return _start(state["project_id"], "loop", "움직임 루프 만들기", _loop_worker, (state, keys, save_fn))


def _loop_worker(job, state, keys, save_fn):
    img = ensure_local(keys, state.get("image") or {}, project_files(state, "image.jpg"))
    if not img:
        raise RuntimeError("그림이 없습니다. 먼저 그림을 만들거나 올려 주세요.")
    mode = state.get("visual_mode", "motion")
    out = project_files(state, "loop.mp4")
    loop = {"mode": mode}
    if mode == "motion":
        from src.video_replicate import generate_single_clip_url
        job["msg"] = "MiniMax 로 6초 움직임 클립 만드는 중 (보통 3~5분)"
        url = generate_single_clip_url(keys.get("REPLICATE_API_TOKEN", ""), motion_prompt_full(state),
                                       image_url=img, prompt_optimizer=False)
        raw = project_files(state, "motion_raw.mp4")
        _download(url, raw)
        loop["raw_local"] = raw
        loop["raw_r2_key"] = keep_in_r2(keys, state, raw, "motion_raw.mp4", "video/mp4")
        job["msg"] = "앞뒤로 이어 붙여 끊김 없는 루프로 인코딩 중"
        build_pingpong_loop(raw, out)
    else:
        job["msg"] = "정지 그림 루프 인코딩 중"
        build_still_loop(img, out)
    loop.update(local=out, seconds=round(duration(out), 2),
                r2_key=keep_in_r2(keys, state, out, "loop.mp4", "video/mp4"))
    state["loop"] = loop
    state["final"] = {}
    _save(save_fn, state)
    job["msg"] = f"완료 — {loop['seconds']}초 루프"


# ── ④ 음악 작업 ──
def start_music_job(state: dict, keys: dict, save_fn, nos: list) -> bool:
    return _start(state["project_id"], "music", "음악 만들기", _music_worker, (state, keys, save_fn, list(nos)))


def _music_worker(job, state, keys, save_fn, nos):
    provider = state.get("provider", "elevenlabs")
    seconds = int(state.get("track_sec", 180))
    by_no = {t["no"]: t for t in state.get("tracks", [])}
    job["total"] = len(nos)
    for i, no in enumerate(nos):
        t = by_no.get(no)
        if t is None:
            continue
        if job["stop"]:
            break
        job["msg"] = f"{i + 1}/{len(nos)}곡 · #{no:02d} {t.get('title_ja', '')} 만드는 중"
        t["status"], t["error"] = "generating", ""
        dest = project_files(state, "music", f"track_{no:02d}.mp3")
        try:
            prompt = track_prompt(state, t, seconds)
            if provider == "lyria":
                _gen_lyria(keys.get("GOOGLE_API_KEY", ""), prompt, dest)
            else:
                _gen_elevenlabs(keys.get("ELEVENLABS_API_KEY", ""), prompt, seconds, dest)
            t.update(status="done", local=dest, seconds=round(duration(dest), 2), source=provider,
                     r2_key=keep_in_r2(keys, state, dest, f"music/track_{no:02d}.mp3", "audio/mpeg"))
            state["final"] = {}
        except StopAll as e:
            t.update(status="error", error=str(e))
            job["error"] = str(e)
            _save(save_fn, state)
            break
        except Exception as e:
            t.update(status="error", error=f"{type(e).__name__}: {e}"[:400])
        job["done"] = i + 1
        job["pct"] = (i + 1) / max(len(nos), 1)
        _save(save_fn, state)
    for t in by_no.values():
        if t.get("status") == "generating":
            t["status"] = "pending"
    _save(save_fn, state)
    ok = sum(1 for t in by_no.values() if t.get("status") == "done")
    job["msg"] = f"끝 — 완성 {ok}곡"


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ 합성
# ─────────────────────────────────────────────────────────────────────────────
def playlist(state: dict) -> list:
    """완성된 곡을 순서대로 놓고, 목표 길이에 못 미치면 처음부터 반복해 채운다."""
    done = [t for t in sorted(state.get("tracks", []), key=lambda x: x["no"])
            if t.get("status") == "done" and t.get("seconds", 0) > XFADE_SEC * 2 + 10]
    if not done:
        return []
    target = int(state.get("target_min", 60)) * 60
    out, total = [], 0.0
    while True:
        for t in done:
            out.append(t)
            total += t["seconds"] - (XFADE_SEC if len(out) > 1 else 0)
            if total >= target:
                return out
        if not state.get("repeat_fill", True):
            return out


def chapters(items: list) -> list:
    """[(시작초, 곡 제목)] — 크로스페이드만큼 앞당겨진 실제 시작 시점."""
    out, t = [], 0.0
    for i, tr in enumerate(items):
        out.append((t, tr.get("title_ja") or tr.get("title_en") or f"Track {tr['no']}"))
        t += tr["seconds"] - XFADE_SEC
    return out


def chapter_text(chs: list, total: float) -> str:
    long = total >= 3600
    lines = []
    for i, (t, title) in enumerate(chs):
        stamp = "00:00" if i == 0 else fmt_time(t, force_hours=long)
        lines.append(f"{stamp} {title}")
    return "\n".join(lines)


def _run_ffmpeg(args: list, total_sec: float, job: dict, label: str, timeout: int = 7200):
    """-progress 로 진행률을 읽으며 ffmpeg 실행."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", *args]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t0 = time.time()
    for line in p.stdout:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                cur = int(line.split("=")[1]) / 1e6
                if total_sec > 0:
                    job["pct"] = min(cur / total_sec, 0.999)
                    job["msg"] = f"{label} · {fmt_time(cur)} / {fmt_time(total_sec)}"
            except ValueError:
                pass
        if job.get("stop"):
            p.kill()
            raise RuntimeError("중지했습니다.")
        if time.time() - t0 > timeout:
            p.kill()
            raise TimeoutError(f"{label} 가 {timeout // 60}분 안에 끝나지 않았습니다.")
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"{label} 실패: {p.stderr.read()[-800:]}")


def start_render_job(state: dict, keys: dict, save_fn) -> bool:
    return _start(state["project_id"], "render", "최종 합성", _render_worker, (state, keys, save_fn))


def _render_worker(job, state, keys, save_fn):
    # 1) 재료 확인 (서버 재시작 뒤면 R2 에서 다시 받기)
    loop = state.get("loop") or {}
    loop_path = ensure_local(keys, loop, project_files(state, "loop.mp4"))
    if not loop_path:
        raise RuntimeError("루프 영상이 없습니다. ③ 움직임 단계를 먼저 끝내 주세요.")
    items = playlist(state)
    if len(items) < 1:
        raise RuntimeError("완성된 곡이 없습니다.")
    uniq = {t["no"]: t for t in items}
    job["msg"] = "곡 파일 확인 중"
    for no, t in uniq.items():
        ext = os.path.splitext(t.get("local") or t.get("r2_key") or ".mp3")[1] or ".mp3"
        if not ensure_local(keys, t, project_files(state, "music", f"track_{no:02d}{ext}")):
            raise RuntimeError(f"#{no:02d} 곡 파일이 없습니다 (서버 재시작으로 사라졌고 R2 보관본도 없음).")

    # 2) 곡마다 음량 맞춤 → 44.1kHz 스테레오 WAV (같은 곡이 반복돼도 한 번만)
    norm = {}
    job["total"] = len(uniq)
    for i, (no, t) in enumerate(uniq.items()):
        job["msg"] = f"음량 맞추는 중 {i + 1}/{len(uniq)}"
        job["pct"] = i / max(len(uniq), 1)
        out = project_files(state, "work", f"norm_{no:02d}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", t["local"], "-af",
                        f"{LOUDNESS},aresample=44100", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out],
                       check=True, timeout=900)
        norm[no] = out
        t["seconds"] = round(duration(out), 2)      # 실제 길이로 보정 (챕터 정확도)
        if job["stop"]:
            raise RuntimeError("중지했습니다.")

    # 3) 크로스페이드 연결 → AAC
    chs = chapters(items)
    total = chs[-1][0] + items[-1]["seconds"]
    music = project_files(state, "work", "music.m4a")
    args = []
    for t in items:
        args += ["-i", norm[t["no"]]]
    if len(items) == 1:
        fc = "[0:a]anull[m]"
    else:
        parts, prev = [], "[0:a]"
        for i in range(1, len(items)):
            lab = f"[x{i}]"
            parts.append(f"{prev}[{i}:a]acrossfade=d={XFADE_SEC}:c1=tri:c2=tri{lab}")
            prev = lab
        fc = ";".join(parts) + f";{prev}anull[m]"
    fc += (f";[m]afade=t=in:st=0:d={FADE_IN_SEC},"
           f"afade=t=out:st={max(total - FADE_OUT_SEC, 0):.2f}:d={FADE_OUT_SEC}[a]")
    _run_ffmpeg([*args, "-filter_complex", fc, "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
                 "-ar", "44100", "-ac", "2", music], total, job, "음악 연결·인코딩")
    total = duration(music) or total

    # 4) 루프 영상을 스트림 복사로 반복 + 음악 → 최종 MP4 (영상은 다시 인코딩하지 않음)
    job["msg"], job["pct"] = "영상 반복 결합 중", 0.0
    final = project_files(state, f"HASIRA_{state.get('project_id', 'final')}.mp4")
    _run_ffmpeg(["-stream_loop", "-1", "-i", loop_path, "-i", music, "-map", "0:v:0", "-map", "1:a:0",
                 "-c", "copy", "-t", f"{total:.3f}", "-movflags", "+faststart", final],
                total, job, "영상 결합")
    for f in norm.values():
        try:
            os.remove(f)
        except OSError:
            pass

    info = {"local": final, "seconds": round(duration(final), 2), "bytes": os.path.getsize(final),
            "chapters": [[round(t, 2), title] for t, title in chs], "made_at": time.strftime("%Y-%m-%d %H:%M")}
    # 5) R2 로 전달
    if _r2_ok(keys):
        job["msg"], job["pct"] = f"R2 에 올리는 중 ({info['bytes'] / 1e6:.0f}MB)", 0.999
        info["r2_key"] = keep_in_r2(keys, state, final, os.path.basename(final), "video/mp4")
    state["final"] = info
    _save(save_fn, state)
    job["msg"], job["pct"] = f"완료 — {fmt_time(info['seconds'], True)} · {info['bytes'] / 1e6:.0f}MB", 1.0


def final_link(keys: dict, state: dict) -> str:
    info = state.get("final") or {}
    if not info.get("r2_key") or not _r2_ok(keys):
        return ""
    from src import r2_store
    return r2_store.download_link(keys, info["r2_key"], filename=os.path.basename(info["r2_key"]))


# ─────────────────────────────────────────────────────────────────────────────
# ⑦ 업로드 정보
# ─────────────────────────────────────────────────────────────────────────────
def make_upload_pack(api_key: str, state: dict) -> dict:
    info = state.get("final") or {}
    chs = [(t, title) for t, title in info.get("chapters", [])]
    total = info.get("seconds", 0)
    plan = state.get("plan") or {}
    pack = {"title": plan.get("title_ja", ""), "description": plan.get("concept_ko", ""), "tags": [], "hashtags": []}
    if api_key:
        import anthropic
        from src.prompts import SCRIPT_MODEL, _text_of, _extract_json
        user = (f"영상 길이: {fmt_time(total, True)}\n기획 제목: {plan.get('title_ja', '')}\n"
                f"장면: {plan.get('concept_ko', '')}\n음악: {plan.get('music_style', '')}\n"
                f"곡 수: {len(set(title for _, title in chs))}곡")
        try:
            resp = anthropic.Anthropic(api_key=api_key).messages.create(
                model=SCRIPT_MODEL, max_tokens=1500, system=PACK_SYSTEM,
                messages=[{"role": "user", "content": user}])
            pack.update({k: v for k, v in _extract_json(_text_of(resp)).items() if v})
        except Exception as e:
            print(f"[hasira] 업로드 정보 생성 실패 → 기획 제목 사용: {e}", flush=True)
    tags = [str(t).strip().lstrip("#") for t in pack.get("tags") or [] if str(t).strip()]
    while tags and len(",".join(tags)) > 480:          # YouTube 태그 칸 합계 500자
        tags.pop()
    pack["tags"] = tags
    hashtags = " ".join(h if str(h).startswith("#") else f"#{h}" for h in (pack.get("hashtags") or [])[:3])
    tracklist = chapter_text(chs, total) if len(chs) >= 3 else ""
    body = pack.get("description", "").strip()
    if tracklist:
        body += "\n\n― Tracklist ―\n" + tracklist
    body += "\n\n※ 音楽・映像は AI ツールで制作しています。"
    if hashtags:
        body += "\n\n" + hashtags
    pack["full_description"] = body.strip()
    state["upload_pack"] = pack
    return pack
