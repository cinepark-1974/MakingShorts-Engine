# src/voice_test.py
# 숏폼 팩토리 — 나레이션 목소리 시험 (SceneStory 일본어 목소리 읽기 속도 측정)
#
# 시험 문장을 실제 목소리로 읽혀 길이(초)를 재고, 초당 글자 수를 계산한다.
# 이 숫자로 SceneStory 대본 글자 수(60~75초)를 정한다.

import json
import os
import re
import subprocess
import tempfile
import time

JA_VOICE_ID = "wcs09USXSN5Bl7FXohVZ"        # SceneStory 일본어 나레이션 (Mr. MOON 선택)
MODEL_ID = "eleven_multilingual_v2"

JA_SAMPLE = (
    "金曜の夜十時。日本中の主婦が、電話に出なかった時代があります。"
    "ドラマの名は『金曜日の妻たちへ』。舞台は、東京郊外の新しい住宅街でした。"
    "あの頃、隣の家の窓には、どんな灯りがともっていたのでしょうか。"
)

_PUNCT = re.compile(r"[\s、。，．・「」『』（）()!?！？…ー―\-]")


def _duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return os.path.getsize(path) * 8 / 128_000      # 128kbps 기준 추정


def test_voice(api_key: str, voice_id: str = JA_VOICE_ID, text: str = JA_SAMPLE) -> dict:
    rep = {"ok": False, "voice_id": voice_id, "model": MODEL_ID, "text": text,
           "chars": len(re.sub(r"\s", "", text)), "chars_no_punct": len(_PUNCT.sub("", text)),
           "seconds": 0.0, "cps": 0.0, "cps_no_punct": 0.0, "audio": b"", "error": "", "elapsed": 0.0}
    if not api_key:
        rep["error"] = "ELEVENLABS_API_KEY 가 Secrets 에 없습니다."
        return rep
    t0 = time.time()
    try:
        from elevenlabs import ElevenLabs
        it = ElevenLabs(api_key=api_key).text_to_speech.convert(
            voice_id=voice_id, text=text, model_id=MODEL_ID, output_format="mp3_44100_128")
        audio = b"".join(it)
        rep["elapsed"] = round(time.time() - t0, 1)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio)
            tmp = f.name
        sec = _duration(tmp)
        os.remove(tmp)
        rep.update(audio=audio, seconds=round(sec, 2), ok=len(audio) > 0)
        if sec > 0:
            rep["cps"] = round(rep["chars"] / sec, 2)
            rep["cps_no_punct"] = round(rep["chars_no_punct"] / sec, 2)
    except Exception as e:
        rep["elapsed"] = round(time.time() - t0, 1)
        rep["error"] = f"{type(e).__name__}: {e}"
    return rep


def result_json(rep: dict) -> bytes:
    keep = {k: v for k, v in rep.items() if k != "audio"}
    keep["audio_bytes"] = len(rep.get("audio") or b"")
    return json.dumps(keep, ensure_ascii=False, indent=2).encode("utf-8")
