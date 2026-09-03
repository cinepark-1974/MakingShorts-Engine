# src/image_gemini.py
# 너도나도아는커피 숏폼 팩토리 — Gemini Imagen 3 수채화 스케치 이미지 생성기
#
# 대상 씬: MACHINE / EXTRACTION / SCIENCE_DATA
# 파이프라인: Gemini Imagen 3 → image bytes → fal.ai CDN 업로드 → 영구 URL 반환
#
# ⚠️ 패키지 주의:
#   google-generativeai (구버전) → deprecated, ImageGenerationModel 없음
#   google-genai (신버전 v2+)   → 이 파일은 이것을 사용
#   requirements.txt 에 google-genai>=0.8.0 이 등록되어 있어야 한다.
#
# Fal.ai CDN에 저장하는 이유:
#   Gemini 응답은 메모리 객체(bytes)이므로 Streamlit Reboot 후 사라진다.
#   fal_client.upload_file()로 CDN에 올리면 URL이 영구적으로 유지된다.
#
# 전제조건:
#   Streamlit secrets.toml 에 GOOGLE_API_KEY 와 FAL_KEY 가 등록되어 있어야 한다.

import os
import tempfile

import fal_client
from google import genai
from google.genai import types as genai_types

# ── 수채화 스케치 스타일 접두사 ──────────────────────────────────────────────
# Gemini Imagen 3 에서 검증 완료 (2026-09-02, 에스프레소 머신 / 추출 포어 / 두 잔 비교 3종 확인)
_WATERCOLOR_PREFIX = (
    "Hand-drawn pen-and-ink sketch illustration, "
    "thin expressive linework with loose imperfect contours, "
    "soft warm watercolor wash fills, subtle paper grain texture visible, "
    "sketchbook aesthetic with slightly unfinished quality, "
    "warm cream and amber coffee tones on off-white paper background, "
    "elegant negative space, artbook quality illustration, "
    "NO photorealism, NO digital painting, NO CGI, NO 3D render, NO anime, "
    "NO human faces, NO people, "
    "PURE VISUAL ZERO TEXT ZERO LABELS ZERO WORDS ZERO NUMBERS. "
)


def generate_illustration_image(
    gemini_key: str,
    fal_key: str,
    image_prompt: str,
    aspect_ratio: str = "9:16",
) -> str:
    """
    Gemini Imagen 3 로 수채화 스케치 이미지를 생성하고 fal CDN URL 을 반환한다.

    Args:
        gemini_key   : GOOGLE_API_KEY (Streamlit secrets)
        fal_key      : FAL_KEY (Streamlit secrets)
        image_prompt : 씬별 영문 프롬프트
        aspect_ratio : 기본 "9:16" (9:16 세로 숏폼)

    Returns:
        str : fal.ai CDN 공개 이미지 URL (Streamlit Reboot 후에도 유효)

    Raises:
        RuntimeError : Gemini 응답에서 이미지를 꺼낼 수 없을 때 (안전 필터 차단 등)
    """
    os.environ["FAL_KEY"] = fal_key

    # ── Gemini Imagen 3 이미지 생성 ─────────────────────────────────────────
    # google-genai v2+ 신규 API 사용
    client = genai.Client(api_key=gemini_key)

    response = client.models.generate_images(
        model="imagen-3.0-generate-002",
        prompt=_WATERCOLOR_PREFIX + image_prompt,
        config=genai_types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_ratio,
            safety_filter_level="BLOCK_ONLY_HIGH",   # BLOCK_SOME 은 유효하지 않은 값
            person_generation="DONT_ALLOW",           # 얼굴/인물 생성 원천 차단
        ),
    )

    # ── image bytes 추출 ─────────────────────────────────────────────────────
    # 응답 구조: response.generated_images[0].image.image_bytes
    if not response.generated_images:
        raise RuntimeError(
            "Gemini Imagen 3: 이미지가 생성되지 않았습니다. "
            "안전 필터 차단 또는 프롬프트 위반 가능성을 확인하세요."
        )

    generated = response.generated_images[0]
    if generated.image is None or not generated.image.image_bytes:
        rai_reason = getattr(generated, "rai_filtered_reason", "알 수 없음")
        raise RuntimeError(
            f"Gemini Imagen 3: 이미지 bytes 를 추출할 수 없습니다. "
            f"RAI 필터 이유: {rai_reason}"
        )

    image_bytes = generated.image.image_bytes
    mime_type   = generated.image.mime_type or "image/png"

    # MIME → 확장자 결정
    ext = ".jpg" if "jpeg" in mime_type else ".png"

    # ── 임시 파일 → fal CDN 업로드 ──────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        cdn_url = fal_client.upload_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    return cdn_url
