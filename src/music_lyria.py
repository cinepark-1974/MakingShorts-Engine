# src/music_lyria.py
# 숏폼 팩토리 — Google Lyria 음악 생성 (연결 테스트 단계)
#
# 공식 문서(Gemini API, Lyria 3.5)의 호출 방식:
#   client.interactions.create(model=..., input="프롬프트")
#   결과 음악: interaction.output_audio.data (base64 MP3)
#   lyria-3-clip-preview = 30초 클립, lyria-3.5 = 2~3분 곡
#
# 지금은 "실제 응답이 어떻게 오는지" 확인하는 테스트만 둔다.
# 이 결과(응답 구조)를 보고 HASIRA 음악 라인을 작성한다.

import base64
import json
import time

CLIP_MODEL = "lyria-3-clip-preview"
SONG_MODEL = "lyria-3.5"
TEST_PROMPT = ("Instrumental only, no vocals. Calm cinematic solo piano with soft strings, "
               "slow tempo around 70 BPM, warm and romantic evening mood.")


def _describe(obj, depth=0):
    """응답 객체의 구조(필드 이름·형식·길이)만 뽑는다. 음악 데이터 자체는 넣지 않는다."""
    if depth > 4:
        return "…"
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(exclude_none=True)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "data" and isinstance(v, (str, bytes)):
                out[k] = f"<{type(v).__name__} {len(v)}자>"
            else:
                out[k] = _describe(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_describe(v, depth + 1) for v in obj[:5]] + (["…"] if len(obj) > 5 else [])
    if isinstance(obj, str) and len(obj) > 200:
        return obj[:200] + "…"
    return obj


def test_clip(api_key: str, prompt: str = TEST_PROMPT, model: str = CLIP_MODEL) -> dict:
    """30초 클립 하나를 받아 본다. 반환: ok, seconds, audio(bytes), mime, structure(dict), error."""
    rep = {"ok": False, "seconds": 0.0, "audio": b"", "mime": "", "structure": {}, "error": "",
           "model": model}
    if not api_key:
        rep["error"] = "GOOGLE_API_KEY 가 Secrets 에 없습니다."
        return rep
    t0 = time.time()
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        inter = client.interactions.create(model=model, input=prompt)
        rep["seconds"] = round(time.time() - t0, 1)
        rep["structure"] = _describe(inter)
        audio = getattr(inter, "output_audio", None)
        if audio is not None and getattr(audio, "data", None):
            raw = audio.data
            rep["audio"] = base64.b64decode(raw) if isinstance(raw, str) else bytes(raw)
            rep["mime"] = getattr(audio, "mime_type", "") or "audio/mpeg"
            rep["ok"] = len(rep["audio"]) > 0
        else:
            rep["error"] = "응답에 output_audio 가 없습니다 — 아래 응답 구조를 확인하세요."
    except Exception as e:
        rep["seconds"] = round(time.time() - t0, 1)
        rep["error"] = f"{type(e).__name__}: {e}"
    return rep


def structure_json(rep: dict) -> bytes:
    keep = {k: rep[k] for k in ("ok", "model", "seconds", "mime", "error", "structure")}
    keep["audio_bytes"] = len(rep.get("audio") or b"")
    return json.dumps(keep, ensure_ascii=False, indent=2, default=str).encode("utf-8")
