# src/sound.py
# 너도나도아는커피 숏폼 팩토리 — 효과음(SFX) · 배경음악(BGM) 준비
#
# 소리 파일을 가져오는 순서
#   1) assets/sfx/<태그>.mp3, assets/bgm/*.mp3 에 직접 올린 파일이 있으면 그것을 쓴다 (무료·확정 음원)
#   2) 이미 만든 적이 있으면 캐시(project_dir/sound/)에서 재사용한다 (재합성할 때 비용 0)
#   3) 없으면 ElevenLabs 로 생성한다
#        효과음 : text_to_sound_effects.convert  (0.5~30초, model eleven_text_to_sound_v2)
#        배경음악: music.compose                 (3초~10분, force_instrumental=True)
#      두 메서드 모두 Iterator[bytes] 를 돌려준다 (elevenlabs SDK 2.x 시그니처 확인).
#
# 어떤 단계가 실패해도 예외를 밖으로 던지지 않고 None 을 돌려준다.
# → 소리가 없어도 영상 합성은 끝까지 진행된다.

import glob
import os

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

# 대본 sfx 태그 → ElevenLabs 효과음 프롬프트, 길이(초)
SFX_LIBRARY = {
    "impact_whoosh": ("fast cinematic whoosh transition ending in a soft deep impact hit", 1.4),
    "tech_beep":     ("two soft clean digital interface blips, minimal UI sound", 0.8),
    "steam_hiss":    ("short espresso machine steam wand hiss burst", 1.8),
    "coffee_pour":   ("coffee pouring into a glass full of ice cubes, close microphone", 2.2),
    "ambient_cafe":  ("quiet coffee shop ambience, soft murmur, cups and saucers clinking", 4.0),
    "deep_bass":     ("single deep cinematic sub bass boom", 1.6),
}

BGM_PROMPT = (
    "Warm lo-fi jazz hop instrumental for a coffee science explainer video. "
    "Soft Rhodes electric piano chords, brushed drums, round upright bass, "
    "steady 84 BPM, calm and curious mood, sits quietly under a voice-over, "
    "no vocals, no sudden drops, gentle ending."
)


def _write_iter(chunks, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        for c in chunks:
            if c:
                f.write(c)
    if os.path.getsize(path) == 0:
        os.remove(path)
        raise RuntimeError("빈 오디오가 반환되었습니다.")
    return path


def _client(api_key: str):
    from elevenlabs import ElevenLabs
    return ElevenLabs(api_key=api_key)


def get_sfx(tag: str, api_key: str, cache_dir: str):
    """태그에 맞는 효과음 파일 경로. 준비할 수 없으면 None."""
    tag = (tag or "").strip().lower()
    if tag not in SFX_LIBRARY:
        return None
    own = os.path.join(ASSETS_DIR, "sfx", f"{tag}.mp3")
    if os.path.exists(own):
        return own
    cached = os.path.join(cache_dir, f"sfx_{tag}.mp3")
    if os.path.exists(cached) and os.path.getsize(cached) > 0:
        return cached
    if not api_key:
        return None
    prompt, dur = SFX_LIBRARY[tag]
    try:
        print(f"[sound] 효과음 생성: {tag}", flush=True)
        audio = _client(api_key).text_to_sound_effects.convert(
            text=prompt,
            duration_seconds=dur,
            prompt_influence=0.5,
            output_format="mp3_44100_128",
        )
        return _write_iter(audio, cached)
    except Exception as e:
        print(f"[sound] 효과음 실패 ({tag}): {e}", flush=True)
        return None


def get_bgm(seconds: float, api_key: str, cache_dir: str):
    """영상 길이에 맞춘 배경음악 파일 경로. 준비할 수 없으면 None."""
    own = sorted(glob.glob(os.path.join(ASSETS_DIR, "bgm", "*.mp3")))
    if own:
        return own[0]
    length_ms = int(max(3000, min(600000, (seconds + 2.0) * 1000)))
    cached = os.path.join(cache_dir, f"bgm_{length_ms // 1000}s.mp3")
    if os.path.exists(cached) and os.path.getsize(cached) > 0:
        return cached
    if not api_key:
        return None
    try:
        print(f"[sound] 배경음악 생성: {length_ms / 1000:.0f}초", flush=True)
        audio = _client(api_key).music.compose(
            prompt=BGM_PROMPT,
            music_length_ms=length_ms,
            force_instrumental=True,
        )
        return _write_iter(audio, cached)
    except Exception as e:
        print(f"[sound] 배경음악 실패: {e}", flush=True)
        return None
