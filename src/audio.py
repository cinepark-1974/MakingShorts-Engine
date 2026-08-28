# src/audio.py
# 너도나도아는커피 숏폼 팩토리 — ElevenLabs 나레이션 음성 생성기
#
# ──────────────────────────────────────────────────────────────────────────────
# [구현 대기 중]
#
# ElevenLabs API의 실제 응답 구조(스트리밍 vs 단일 바이트, 헤더 형식 등)를
# 실제 호출 샘플로 확인한 뒤 아래 TODO 구간을 채워야 합니다.
#
# 확인이 필요한 항목:
#   1. elevenlabs SDK v1.x 에서 text_to_speech.convert() 반환 타입
#      (제너레이터 / bytes / 파일 객체 등)
#   2. 사용할 음성 ID (voice_id) — ElevenLabs 콘솔에서 사전 확보 필요
#   3. 한국어 지원 모델 ID (예: eleven_multilingual_v2)
#   4. 청크 스트리밍 저장 방식 확인
# ──────────────────────────────────────────────────────────────────────────────

import os


# TODO: 실제 음성 ID를 ElevenLabs 콘솔(Voices 탭)에서 확인 후 교체
DEFAULT_VOICE_ID = "VOICE_ID_HERE"

# TODO: 한국어 지원 모델 ID 확인 (2024년 기준 eleven_multilingual_v2 권장)
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


def generate_narration(
    api_key: str,
    text: str,
    output_path: str,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
) -> str:
    """
    ElevenLabs API로 전체 나레이션 텍스트를 MP3 음성 파일로 변환한다.

    Args:
        api_key     : ELEVENLABS_API_KEY
        text        : 나레이션 전체 텍스트 (full_narration)
        output_path : 저장할 .mp3 파일 경로
        voice_id    : ElevenLabs 음성 ID
        model_id    : ElevenLabs 모델 ID

    Returns:
        str : 저장된 로컬 파일 경로 (= output_path)

    Raises:
        NotImplementedError : 아직 구현되지 않은 상태
    """
    # ── 구현 전 가드 ──────────────────────────────────────────────────────────
    raise NotImplementedError(
        "src/audio.py 는 아직 구현되지 않았습니다.\n"
        "ElevenLabs API 응답 샘플 확인 후 이 함수를 완성하세요."
    )

    # ── TODO: 아래 코드를 실제 API 응답 구조에 맞게 완성 ───────────────────────
    # from elevenlabs import ElevenLabs
    #
    # client = ElevenLabs(api_key=api_key)
    #
    # audio = client.text_to_speech.convert(
    #     voice_id=voice_id,
    #     text=text,
    #     model_id=model_id,
    #     output_format="mp3_44100_128",
    # )
    #
    # os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
    # with open(output_path, "wb") as f:
    #     for chunk in audio:          # 반환 타입이 제너레이터인 경우
    #         f.write(chunk)
    #
    # return output_path
