# src/image_fal.py
# 너도나도아는커피 숏폼 팩토리 — 레퍼런스 이미지 생성기 (혼합 전략 v3)
#
# ┌─────────────────────────────────────────────────────────────┐
# │ ASSEMBLY              → fal-ai/flux-pro                     │
# │                         포토리얼 음식사진 스타일               │
# │                                                             │
# │ MACHINE               → Gemini Imagen 3                     │
# │ EXTRACTION               수채화 펜-잉크 스케치 일러스트 스타일  │
# │ SCIENCE_DATA             (FLUX는 스케치 불가 → Gemini로 교체) │
# └─────────────────────────────────────────────────────────────┘
# 생성된 이미지는 fal.ai CDN URL로 저장 (로컬 다운로드 없음 → Reboot 후에도 상태 유지)

import os
import fal_client

from src.image_gptimage2 import generate_illustration_image


# ── 모델 ID ───────────────────────────────────────────────────────────────────
FLUX_PRO_MODEL = "fal-ai/flux-pro"   # 28-step | 포토리얼 씬 (ASSEMBLY 음식사진)
FLUX_DEV_MODEL = "fal-ai/flux/dev"   # 28-step | Gemini 실패 시 폴백용

# ── 씬 타입 → 렌더링 엔진 라우팅 ─────────────────────────────────────────────
_ASSEMBLY_TYPES = {"ASSEMBLY"}
_ILLUST_TYPES   = {"MACHINE", "EXTRACTION", "SCIENCE_DATA"}   # → Gemini Imagen 3
_PHOTO_TYPES    = {"CINEMATIC", "ORIGIN_MAP"}                 # Unsplash 처리 — 여기서 생성 안 함

# ── 접두사 ────────────────────────────────────────────────────────────────────
# ASSEMBLY (포토리얼): 텍스트/레이블 완전 금지만 선언
_NO_TEXT_PREFIX = (
    "PURE VISUAL ONLY. ABSOLUTELY ZERO TEXT. ZERO LABELS. ZERO WORDS. "
    "ZERO NUMBERS. ZERO LETTERS. ZERO WATERMARKS. ZERO CAPTIONS. "
    "NO TYPOGRAPHY OF ANY KIND. "
)

# MACHINE / EXTRACTION / SCIENCE_DATA (수채화 스케치): 스타일 선언 + 텍스트 금지
# 언캐니밸리를 피하기 위해 포토리얼 대신 펜-잉크 수채화 스케치로 렌더링한다.
# 제미나이 테스트에서 커피 씬 3종 모두 검증 완료 (2026-09-02)
_ILLUST_PREFIX = (
    "Hand-drawn pen-and-ink sketch illustration, "
    "thin expressive linework with loose imperfect contours, "
    "soft warm watercolor wash fills, subtle paper grain texture visible, "
    "sketchbook aesthetic with slightly unfinished quality, "
    "warm cream and amber coffee tones on off-white paper background, "
    "elegant negative space, artbook quality illustration, "
    "NO photorealism, NO digital painting, NO CGI, NO 3D render, NO anime, "
    "PURE VISUAL ZERO TEXT ZERO LABELS ZERO WORDS ZERO NUMBERS. "
)


def generate_reference_image(
    fal_key: str,
    image_prompt: str,
    output_path: str = "",      # 하위 호환용 — 더 이상 로컬 저장 안 함
    width: int = 720,
    height: int = 1280,
    model: str = "",            # 빈 문자열 → FLUX_DEV_MODEL 사용
    illust_mode: bool = False,  # True → 일러스트 접두사 / False → NO_TEXT 접두사
) -> str:
    """
    Fal.ai FLUX로 레퍼런스 이미지를 생성하고 fal CDN URL을 반환한다.
    로컬에 다운로드하지 않으므로 Streamlit Reboot 후에도 URL이 유효하다.

    Args:
        fal_key      : FAL_KEY (Fal.ai API 키)
        image_prompt : 씬별 프롬프트 (영문)
        output_path  : (미사용, 하위 호환 유지용)
        width        : 이미지 너비 (기본 720 — 9:16 세로)
        height       : 이미지 높이 (기본 1280 — 9:16 세로)
        model        : 사용할 FLUX 모델 ID (기본: FLUX_DEV_MODEL)
        illust_mode  : True면 일러스트 접두사, False면 NO_TEXT 접두사

    Returns:
        str : fal.ai CDN 공개 이미지 URL
    """
    os.environ["FAL_KEY"] = fal_key

    chosen_model = model or FLUX_DEV_MODEL
    prefix = _ILLUST_PREFIX if illust_mode else _NO_TEXT_PREFIX
    enforced_prompt = prefix + image_prompt

    # FLUX dev / FLUX pro 공통 파라미터
    # num_inference_steps 28 = 품질과 속도의 균형점
    # guidance_scale 3.5 = FLUX 권장 범위 (2.5~4.5)
    arguments = {
        "prompt":              enforced_prompt,
        "image_size":          {"width": width, "height": height},
        "num_inference_steps": 28,
        "guidance_scale":      3.5,
        "num_images":          1,
        "output_format":       "jpeg",
    }

    handler = fal_client.submit(chosen_model, arguments=arguments)
    result  = handler.get()

    # fal-ai/flux 공통 응답 구조: result["images"][0]["url"]
    return result["images"][0]["url"]


def generate_images_for_scenes(
    fal_key: str,
    scenes: list,
    project_dir: str = "",
    gemini_key: str = "",
) -> list:
    """
    여러 씬의 프롬프트를 순차적으로 생성한다.

    라우팅 규칙:
      ASSEMBLY               → flux-pro + NO_TEXT 접두사 (포토리얼 음식사진)
      MACHINE / EXTRACTION
      SCIENCE_DATA           → Gemini Imagen 3 (수채화 펜-잉크 스케치)
                               gemini_key 미제공 시 flux-dev 로 폴백
      CINEMATIC / ORIGIN_MAP → 건너뜀 (Unsplash 실사 처리)
      image_status == 'done' → 건너뜀 (이미 생성 완료)
    """
    for scene in scenes:
        scene_type    = scene.get("scene_type", "")
        visual_source = scene.get("visual_source", "ai")

        # 실사 씬(photo)은 Unsplash에서 처리 — 여기서 생성 안 함
        if visual_source == "photo" or scene_type in _PHOTO_TYPES:
            continue

        prompt = (scene.get("image_prompt") or scene.get("flow_prompt") or "").strip()
        if not prompt:
            continue
        if scene.get("image_status") == "done":
            continue

        scene["image_status"] = "generating"

        try:
            if scene_type in _ASSEMBLY_TYPES:
                # ── ASSEMBLY: FLUX Pro 포토리얼 음식사진 ──────────────────
                url = generate_reference_image(
                    fal_key=fal_key,
                    image_prompt=prompt,
                    model=FLUX_PRO_MODEL,
                    illust_mode=False,
                )

            elif scene_type in _ILLUST_TYPES:
                # ── MACHINE / EXTRACTION / SCIENCE_DATA: GPT Image 2 수채화 스케치 ─
                # FAL_KEY 하나로 사용 — Enterprise 제한 없음
                try:
                    url = generate_illustration_image(
                        fal_key=fal_key,
                        image_prompt=prompt,
                    )
                except Exception:
                    # GPT Image 2 실패 시 FLUX Dev 일러스트 모드로 폴백
                    url = generate_reference_image(
                        fal_key=fal_key,
                        image_prompt=prompt,
                        model=FLUX_DEV_MODEL,
                        illust_mode=True,
                    )

            else:
                # ── 폴백: Gemini 키 없거나 알 수 없는 ai 씬 → flux-dev ────
                url = generate_reference_image(
                    fal_key=fal_key,
                    image_prompt=prompt,
                    model=FLUX_DEV_MODEL,
                    illust_mode=True,
                )

            scene["image_path"]          = url   # fal CDN URL
            scene["image_status"]        = "done"
            scene["reference_image_url"] = url
            scene.pop("image_error", None)

        except Exception as e:
            scene["image_status"] = "error"
            scene["image_error"]  = str(e)

    return scenes
