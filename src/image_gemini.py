# src/image_gemini.py
# 너도나도아는커피 숏폼 팩토리 — Gemini Imagen 3 수채화 스케치 이미지 생성기
#
# 대상 씬: MACHINE / EXTRACTION / SCIENCE_DATA
# 파이프라인: Gemini Imagen 3 → 이미지 bytes → fal.ai CDN 업로드 → 영구 URL 반환
#
# Fal.ai CDN에 저장하는 이유:
#   Gemini 응답은 메모리 객체(bytes)이므로 Streamlit Reboot 후 사라진다.
#   fal_client.upload_file()로 CDN에 올리면 URL이 영구적으로 유지된다.
#
# 전제조건:
#   Streamlit secrets.toml 에 GOOGLE_API_KEY 와 FAL_KEY 가 등록되어 있어야 한다.

import io
import os
import tempfile

import fal_client
import google.generativeai as genai
from google.generativeai import types as genai_types

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
        RuntimeError : Gemini 응답에서 이미지를 꺼낼 수 없을 때
    """
    # ── Gemini 설정 ──────────────────────────────────────────────────────────
    genai.configure(api_key=gemini_key)
    os.environ["FAL_KEY"] = fal_key

    # ── Imagen 3 이미지 생성 ─────────────────────────────────────────────────
    imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")
    response = imagen.generate_images(
        prompt=_WATERCOLOR_PREFIX + image_prompt,
        number_of_images=1,
        aspect_ratio=aspect_ratio,
        safety_filter_level="block_some",
        person_generation="dont_allow",   # 사람 생성 차단 (얼굴 없음 규칙 강제)
    )

    # ── 이미지 bytes 추출 ────────────────────────────────────────────────────
    if not response.images:
        raise RuntimeError("Gemini Imagen 3: 이미지가 생성되지 않았습니다. 안전 필터 차단 가능성을 확인하세요.")

    generated_image = response.images[0]

    # google-generativeai SDK 버전에 따라 접근 방식이 다를 수 있음
    # _pil_image 가 있으면 PIL → bytes, 없으면 .image_bytes 직접 사용
    if hasattr(generated_image, "_pil_image") and generated_image._pil_image is not None:
        buf = io.BytesIO()
        generated_image._pil_image.save(buf, format="JPEG", quality=92)
        image_bytes = buf.getvalue()
    elif hasattr(generated_image, "image_bytes") and generated_image.image_bytes:
        image_bytes = generated_image.image_bytes
    else:
        raise RuntimeError("Gemini Imagen 3: 이미지 bytes 를 추출할 수 없습니다.")

    # ── 임시 파일 → fal CDN 업로드 ──────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        cdn_url = fal_client.upload_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    return cdn_url
