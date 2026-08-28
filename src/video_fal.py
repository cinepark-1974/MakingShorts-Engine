# src/video_fal.py
# 너도나도아는커피 숏폼 팩토리 — Fal.ai Kling v2.6 Pro 비디오 생성기
# text-to-video / image-to-video 모두 지원

import os
import io
import requests
import fal_client


# ── Kling 모델 ID (fal.ai) ────────────────────────────────────────────────────
KLING_TEXT_MODEL  = "fal-ai/kling-video/v2.6/pro/text-to-video"
KLING_IMAGE_MODEL = "fal-ai/kling-video/v2.6/pro/image-to-video"

# 기본 생성 옵션
DEFAULT_DURATION = "5"    # 초
DEFAULT_ASPECT   = "9:16" # 세로 숏폼


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼: 로컬 파일 → fal.ai 업로드 URL 변환
# ─────────────────────────────────────────────────────────────────────────────
def _local_to_fal_url(local_path: str) -> str:
    """
    로컬 이미지 파일을 fal.ai 스토리지에 업로드하고 CDN URL을 반환한다.
    Flux로 생성한 PNG를 Kling image-to-video 첫 프레임으로 사용할 때 호출된다.

    Args:
        local_path : 로컬 이미지 파일 경로 (.png / .jpg / .jpeg / .webp)

    Returns:
        str : fal.ai CDN URL
    """
    ext = os.path.splitext(local_path)[1].lower()
    mime_map = {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    content_type = mime_map.get(ext, "image/png")

    with open(local_path, "rb") as f:
        image_bytes = f.read()

    return fal_client.upload(image_bytes, content_type)


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼: 구글 드라이브 URL → fal.ai 업로드 URL 변환
# ─────────────────────────────────────────────────────────────────────────────
def _gdrive_file_id(url: str) -> str | None:
    """구글 드라이브 URL에서 파일 ID를 추출한다.
    지원 형식:
      - https://drive.google.com/file/d/{FILE_ID}/view
      - https://drive.google.com/open?id={FILE_ID}
      - https://drive.google.com/uc?id={FILE_ID}
    """
    import re
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def _gdrive_to_fal_url(gdrive_url: str, timeout: int = 60) -> str:
    """
    구글 드라이브 공유 URL → 이미지 바이트 다운로드 → fal.ai 스토리지에 업로드 → fal URL 반환.

    구글 드라이브 파일은 Fal.ai 서버가 직접 접근하기 어려운 경우가 있으므로
    로컬(Streamlit 서버)에서 한 번 다운로드한 뒤 fal.ai에 재업로드하는 방식을 사용한다.

    Args:
        gdrive_url : 구글 드라이브 공유 URL (공개 설정 필요)
        timeout    : 다운로드 타임아웃 (초)

    Returns:
        str : fal.ai CDN URL (Kling image_url 파라미터에 직접 사용 가능)

    Raises:
        ValueError          : 파일 ID를 추출하지 못한 경우
        requests.HTTPError  : 드라이브 파일 다운로드 실패
    """
    file_id = _gdrive_file_id(gdrive_url)
    if not file_id:
        raise ValueError(
            f"구글 드라이브 URL에서 파일 ID를 추출할 수 없습니다: {gdrive_url}\n"
            "URL 형식: https://drive.google.com/file/d/{{FILE_ID}}/view"
        )

    # 직접 다운로드 URL
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    resp = requests.get(download_url, stream=True, timeout=timeout)
    resp.raise_for_status()

    # Content-Type으로 MIME 타입 판별 (없으면 jpeg로 가정)
    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()

    image_bytes = resp.content
    if len(image_bytes) < 1024:
        # 드라이브 바이러스 경고 페이지 → 직접 다운로드 우회
        confirm_url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
        resp2 = requests.get(confirm_url, stream=True, timeout=timeout)
        resp2.raise_for_status()
        image_bytes = resp2.content
        content_type = resp2.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()

    # fal.ai 스토리지에 업로드
    fal_url = fal_client.upload(image_bytes, content_type=content_type)
    return fal_url


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 단일 클립 생성
# ─────────────────────────────────────────────────────────────────────────────
def generate_single_clip(
    fal_key: str,
    prompt: str,
    output_path: str,
    image_url: str = "",
) -> str:
    """
    Fal.ai Kling v2.6 Pro로 MP4 영상을 생성하여 로컬에 저장한다.

    image_url이 있으면 image-to-video 모드(첫 프레임 지정),
    없으면 text-to-video 모드로 동작한다.

    Args:
        fal_key     : FAL_KEY (Fal.ai API 키)
        prompt      : Kling 영문 비디오 프롬프트
        output_path : 저장할 .mp4 파일 경로
        image_url   : (선택) 구글 드라이브 공유 URL 또는 일반 이미지 URL.
                      비워두면 텍스트 전용 모드.

    Returns:
        str : 저장된 로컬 파일 경로 (= output_path)

    Raises:
        KeyError          : Fal.ai 응답에 video.url 필드가 없을 때
        requests.HTTPError: 영상 파일 다운로드 실패 시
        ValueError        : 구글 드라이브 URL 파싱 실패 시
    """
    os.environ["FAL_KEY"] = fal_key

    # ── 모드 결정 ──────────────────────────────────────────────────────────
    use_image_mode = bool(image_url and image_url.strip())

    if use_image_mode:
        # 이미지 소스 판별: 로컬 파일 → fal 업로드 / 드라이브 → 변환 / 공개 URL → 그대로
        if os.path.isfile(image_url):
            fal_image_url = _local_to_fal_url(image_url)
        elif "drive.google.com" in image_url:
            fal_image_url = _gdrive_to_fal_url(image_url)
        else:
            fal_image_url = image_url  # 이미 공개 URL

        model = KLING_IMAGE_MODEL
        arguments = {
            "prompt":       prompt,
            "image_url":    fal_image_url,
            "duration":     DEFAULT_DURATION,
            "aspect_ratio": DEFAULT_ASPECT,
        }
    else:
        model = KLING_TEXT_MODEL
        arguments = {
            "prompt":       prompt,
            "duration":     DEFAULT_DURATION,
            "aspect_ratio": DEFAULT_ASPECT,
        }

    # ── Fal.ai 비동기 큐 제출 → 완료 대기 ──────────────────────────────────
    handler = fal_client.submit(model, arguments=arguments)
    result  = handler.get()

    # ── 응답에서 영상 URL 추출 ───────────────────────────────────────────────
    video_url = result["video"]["url"]

    # ── 영상 다운로드 → 로컬 저장 ──────────────────────────────────────────
    resp = requests.get(video_url, stream=True, timeout=120)
    resp.raise_for_status()

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 다중 씬 순차 생성
# ─────────────────────────────────────────────────────────────────────────────
def generate_clips_parallel(fal_key: str, scenes: list, project_dir: str) -> list:
    """
    여러 씬을 순차적으로 생성한다.
    씬에 'reference_image_url' 키가 있으면 image-to-video 모드로 생성한다.

    Args:
        fal_key     : FAL_KEY
        scenes      : state["scenes"] 리스트
        project_dir : 프로젝트 디렉터리 경로

    Returns:
        list : 업데이트된 scenes 리스트
    """
    for scene in scenes:
        if scene.get("status") not in ("pending", "error"):
            continue

        sno      = scene["scene_no"]
        out_path = os.path.join(project_dir, f"scene_{sno:02d}.mp4")
        ref_img  = scene.get("reference_image_url", "")  # 드라이브 URL or 빈 문자열
        scene["status"] = "generating"

        try:
            generate_single_clip(
                fal_key=fal_key,
                prompt=scene.get("flow_prompt", ""),
                output_path=out_path,
                image_url=ref_img,
            )
            scene["video_url"] = out_path
            scene["status"]    = "done"
            scene.pop("error_msg", None)
        except Exception as e:
            scene["status"]    = "error"
            scene["error_msg"] = str(e)

    return scenes
