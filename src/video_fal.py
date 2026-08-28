# src/video_fal.py
# 너도나도아는커피 숏폼 팩토리 — Fal.ai Kling v2.6 Pro 비디오 생성기

import os
import requests
import fal_client


# Kling 모델 ID (fal.ai)
KLING_MODEL = "fal-ai/kling-video/v2.6/pro/text-to-video"

# 기본 생성 옵션
DEFAULT_DURATION    = "5"    # 초
DEFAULT_ASPECT      = "9:16" # 세로 숏폼


def generate_single_clip(fal_key: str, prompt: str, output_path: str) -> str:
    """
    Fal.ai Kling v2.6 Pro 로 텍스트 프롬프트 → MP4 영상을 생성하여 로컬에 저장한다.

    Args:
        fal_key     : FAL_KEY (Fal.ai API 키)
        prompt      : Kling 영문 비디오 프롬프트
        output_path : 저장할 .mp4 파일 경로

    Returns:
        str : 저장된 로컬 파일 경로 (= output_path)

    Raises:
        KeyError          : Fal.ai 응답에 video.url 필드가 없을 때
        requests.HTTPError: 영상 파일 다운로드 실패 시
    """
    os.environ["FAL_KEY"] = fal_key

    # 비동기 큐 제출 → 완료 대기
    handler = fal_client.submit(
        KLING_MODEL,
        arguments={
            "prompt":       prompt,
            "duration":     DEFAULT_DURATION,
            "aspect_ratio": DEFAULT_ASPECT,
        },
    )
    result = handler.get()

    # 응답에서 영상 URL 추출
    video_url = result["video"]["url"]

    # 영상 다운로드 → 로컬 저장
    resp = requests.get(video_url, stream=True, timeout=120)
    resp.raise_for_status()

    os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return output_path


def generate_clips_parallel(fal_key: str, scenes: list, project_dir: str) -> list:
    """
    여러 씬을 순차적으로 생성한다 (Streamlit 환경의 스레드 안전성을 위해 순차 처리).
    각 씬의 status 와 video_url 을 업데이트하여 반환한다.

    Args:
        fal_key     : FAL_KEY
        scenes      : state["scenes"] 리스트 (status == "pending" 인 씬만 처리)
        project_dir : 프로젝트 디렉터리 경로

    Returns:
        list : 업데이트된 scenes 리스트
    """
    for scene in scenes:
        if scene.get("status") not in ("pending", "error"):
            continue

        sno = scene["scene_no"]
        out_path = os.path.join(project_dir, f"scene_{sno:02d}.mp4")
        scene["status"] = "generating"

        try:
            generate_single_clip(
                fal_key=fal_key,
                prompt=scene.get("flow_prompt", ""),
                output_path=out_path,
            )
            scene["video_url"] = out_path
            scene["status"]    = "done"
            scene.pop("error_msg", None)
        except Exception as e:
            scene["status"]    = "error"
            scene["error_msg"] = str(e)

    return scenes
