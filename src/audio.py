# src/audio.py
# 너도나도아는커피 숏폼 팩토리 — ElevenLabs 나레이션 음성 생성기
# v2: fal CDN 업로드 제거 → 로컬 project_dir에 narration.mp3 저장

import os
from elevenlabs import ElevenLabs

DEFAULT_MODEL_ID  = "eleven_v4"                 # 2026-10 기본 (공식 문서: 최고 품질·내레이션용, 한국어·일본어 지원)
FALLBACK_MODEL_ID = "eleven_multilingual_v2"    # v4 가 이 계정·목소리에서 실패하면 되돌림
TTS_MODELS = {"eleven_v4": "eleven_v4 (기본)", "eleven_multilingual_v2": "multilingual_v2 (예전)"}
DEFAULT_VOICE_ID  = "8jHHF8rMqMlg8if2mOUe"


def generate_narration(
    api_key: str,
    text: str,
    output_path: str,
    voice_id: str  = DEFAULT_VOICE_ID,
    model_id: str  = DEFAULT_MODEL_ID,
    info: dict = None,
) -> str:
    """
    ElevenLabs API로 나레이션 텍스트를 MP3 파일로 변환해 로컬에 저장한다.

    Args:
        api_key     : ELEVENLABS_API_KEY
        text        : 나레이션 전체 텍스트
        output_path : 저장할 .mp3 경로
        voice_id    : ElevenLabs 음성 ID
        model_id    : ElevenLabs 모델 ID

    Returns:
        str : 저장된 로컬 파일 경로 (= output_path)
    """
    client = ElevenLabs(api_key=api_key)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    tried = [model_id] + ([FALLBACK_MODEL_ID] if model_id != FALLBACK_MODEL_ID else [])
    last = None
    for mid in tried:
        try:
            audio = b"".join(client.text_to_speech.convert(
                voice_id=voice_id, text=text, model_id=mid, output_format="mp3_44100_128"))
            if not audio:
                raise RuntimeError("빈 음성이 반환되었습니다.")
            with open(output_path, "wb") as f:
                f.write(audio)
            if info is not None:
                info["model"] = mid
                if mid != model_id:
                    info["fallback_reason"] = str(last)[:300]
            return output_path
        except Exception as e:
            last = e
            print(f"[audio] {mid} 실패: {e}", flush=True)
    raise last


def generate_narration_cdn(
    api_key: str,
    text: str,
    fal_key: str,        # 하위 호환 — 현재는 미사용 (fal CDN 대신 로컬 저장)
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
    project_dir: str = "",
    info: dict = None,
) -> str:
    """
    나레이션을 생성하고 로컬 project_dir에 narration.mp3로 저장한 뒤 경로를 반환한다.

    이전 버전은 fal CDN v3에 업로드를 시도했으나, fal CDN v3은 오디오 타입을
    허용하지 않아 403 오류가 발생했다. 이 버전은 로컬 저장만 사용한다.

    assembler.py의 _copy_or_download()는 로컬 경로도 shutil.copy2()로 처리하므로
    CDN URL 없이도 합성 가능하다.

    Args:
        api_key     : ELEVENLABS_API_KEY
        text        : full_narration 텍스트
        fal_key     : (미사용) 하위 호환용
        voice_id    : ElevenLabs 음성 ID
        model_id    : ElevenLabs 모델 ID
        project_dir : 프로젝트 디렉터리 경로 (비어 있으면 /tmp 사용)

    Returns:
        str : 저장된 로컬 MP3 파일 경로
    """
    if project_dir:
        save_dir = project_dir
    else:
        save_dir = "/tmp"

    os.makedirs(save_dir, exist_ok=True)
    output_path = os.path.join(save_dir, "narration.mp3")

    return generate_narration(
        api_key=api_key,
        text=text,
        output_path=output_path,
        voice_id=voice_id,
        model_id=model_id,
        info=info,
    )
