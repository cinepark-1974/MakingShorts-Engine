# src/audio.py
# 너도나도아는커피 숏폼 팩토리 — ElevenLabs 나레이션 음성 생성기
# elevenlabs SDK v1.x 기준 — convert() 반환값: Iterator[bytes]

import os
from elevenlabs.client import ElevenLabs


# ── 기본값 ────────────────────────────────────────────────────────────────────
# ElevenLabs 콘솔(Voices 탭)에서 원하는 음성 ID로 교체하거나
# Streamlit Secrets에 ELEVENLABS_VOICE_ID를 등록하면 그 값을 우선 사용한다.
# 아래 기본값은 한국어 발음이 자연스러운 "Rachel" 다국어 음성 ID.
DEFAULT_VOICE_ID = "9vTWeZwjAkqIiZJdCarV"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_FORMAT   = "mp3_44100_128"


def generate_narration(
    api_key: str,
    text: str,
    output_path: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
) -> str:
    """
    ElevenLabs API로 나레이션 텍스트를 MP3 음성 파일로 변환한다.
    (하위 호환 유지용 — 로컬 저장)

    Returns:
        str : 저장된 로컬 파일 경로 (= output_path)
    """
    client = ElevenLabs(api_key=api_key)

    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format=DEFAULT_FORMAT,
    )

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "wb") as f:
        for chunk in audio_iter:
            f.write(chunk)

    return output_path


def generate_narration_cdn(
    api_key: str,
    text: str,
    fal_key: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
) -> str:
    """
    ElevenLabs로 MP3를 생성하고 fal.ai CDN에 업로드한 뒤 공개 URL을 반환한다.
    Streamlit Cloud 리부트 후에도 URL이 유효하므로 로컬 저장 불필요.

    Args:
        api_key  : ELEVENLABS_API_KEY
        text     : 나레이션 전체 텍스트
        fal_key  : FAL_KEY (fal.ai 업로드용)
        voice_id : ElevenLabs 음성 ID
        model_id : ElevenLabs 모델 ID

    Returns:
        str : fal.ai CDN 공개 URL (state["audio_path"]에 저장)
    """
    import fal_client

    os.environ["FAL_KEY"] = fal_key

    client = ElevenLabs(api_key=api_key)

    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format=DEFAULT_FORMAT,
    )

    # 청크 조립 → bytes
    audio_bytes = b"".join(chunk for chunk in audio_iter)

    # fal.ai CDN 업로드
    cdn_url = fal_client.upload(audio_bytes, content_type="audio/mpeg")
    return cdn_url
