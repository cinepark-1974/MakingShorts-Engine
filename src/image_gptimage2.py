# src/image_gptimage2.py
# 너도나도아는커피 숏폼 팩토리 — GPT Image 2 수채화 스케치 이미지 생성기
#
# 대상 씬: MACHINE / EXTRACTION / SCIENCE_DATA
# 파이프라인: fal.ai openai/gpt-image-2 → fal CDN URL 반환
#
# ✅ Gemini Imagen 3 (Enterprise 전용) 대체 모델
# ✅ FAL_KEY 하나로 사용 가능 — 추가 API 키 불필요
# ✅ portrait_16_9 프리셋 = 576×1024 = 정확히 9:16 세로
#
# 비용 (medium 기준): 이미지 1장 ≈ $0.042
#
# 전제조건:
#   Streamlit secrets.toml 에 FAL_KEY 가 등록되어 있어야 한다.

import os
import fal_client

# ── 수채화 스케치 스타일 접두사 ──────────────────────────────────────────────
# GPT Image 2 검증 완료 (2026-09-03, 에스프레소 머신 단면 컷어웨이 확인)
# 핵심 요소: 펜-잉크 선 + 수채화 워시 + 구리/앰버 커피 톤 + 단면 단순화
_WATERCOLOR_PREFIX = (
    "Technical cutaway cross-section illustration in pen-and-ink sketch style, "
    "precise architectural linework with warm watercolor wash fills, "
    "copper and amber tones for internal components, "
    "cream and off-white paper background with subtle watercolor staining, "
    "clean negative space around the subject, "
    "detailed mechanical interior visible through transparent outer shell, "
    "artbook quality with sketchbook aesthetic, slightly unfinished hand-drawn quality, "
    "NO photorealism, NO 3D render, NO digital painting, NO CGI, NO anime, "
    "NO human faces, NO people, NO text, NO labels, NO numbers, NO watermarks. "
)


def generate_illustration_image(
    fal_key: str,
    image_prompt: str,
    quality: str = "medium",   # "low" | "medium" | "high"
    gemini_key: str = "",      # 하위 호환용 — 사용하지 않음
) -> str:
    """
    fal.ai GPT Image 2 로 수채화 스케치 이미지를 생성하고 fal CDN URL 을 반환한다.

    Args:
        fal_key      : FAL_KEY (Streamlit secrets)
        image_prompt : 씬별 영문 프롬프트
        quality      : "low" / "medium" / "high" (기본 "medium" ≈ $0.042)
        gemini_key   : 미사용 — image_gemini.py 와 호환되는 시그니처 유지용

    Returns:
        str : fal.ai CDN 공개 이미지 URL

    Raises:
        RuntimeError : fal.ai 응답에서 이미지 URL 을 꺼낼 수 없을 때
    """
    os.environ["FAL_KEY"] = fal_key

    handler = fal_client.submit(
        "openai/gpt-image-2",
        arguments={
            "prompt":        _WATERCOLOR_PREFIX + image_prompt,
            "image_size":    "portrait_16_9",   # 576×1024 = 9:16 세로
            "quality":       quality,
            "num_images":    1,
            "output_format": "jpeg",
        },
    )
    result = handler.get()

    try:
        return result["images"][0]["url"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"GPT Image 2: 이미지 URL 을 꺼낼 수 없습니다. "
            f"응답 구조를 확인하세요. 원인: {e}\n원본 응답: {result}"
        )
