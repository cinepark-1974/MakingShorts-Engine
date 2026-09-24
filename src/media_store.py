# src/media_store.py
# 너도나도아는커피 숏폼 팩토리 — 생성 파일 보관
#
# 왜 필요한가:
#   Replicate 는 API 로 만든 결과 파일(replicate.delivery 주소)을 1시간 뒤 자동 삭제한다.
#   (Replicate 공식 문서: "automatically removed after an hour")
#   이미지를 만들고 1시간 넘게 지난 뒤 영상을 만들면 이미지 주소가 404 가 나서 실패했다.
#
#   이 모듈은 이미지·영상 클립이 만들어지는 즉시 project_dir/media/ 에 내려받아 둔다.
#   이후 단계(영상 생성, 미리보기, 최종 합성)는 이 로컬 파일을 먼저 쓴다.
#
#   한계: Streamlit Cloud 서버가 재시작되면 로컬 파일도 사라진다.
#         그 뒤 JSON 으로 복구한 프로젝트는 1시간 지난 Replicate 파일을 다시 받을 수 없다.

import os
import requests


def _media_dir(project_dir: str) -> str:
    d = os.path.join(project_dir or "projects/tmp", "media")
    os.makedirs(d, exist_ok=True)
    return d


def _download(url: str, dest: str, timeout: int = 120) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return os.path.getsize(dest) > 0
    except Exception as e:
        print(f"[media_store] 다운로드 실패 {url[:70]}…: {e}", flush=True)
        if os.path.exists(dest):
            os.remove(dest)
        return False


def is_usable(path: str) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def image_source(scene: dict) -> str:
    """미리보기·영상 생성에 쓸 이미지 (로컬 사본 우선)."""
    local = scene.get("image_local", "")
    if is_usable(local):
        return local
    return scene.get("reference_image_url") or scene.get("image_path") or ""


def video_source(scene: dict) -> str:
    """미리보기·합성에 쓸 영상 클립 (로컬 사본 우선)."""
    local = scene.get("video_local", "")
    if is_usable(local):
        return local
    return scene.get("video_url", "")


def keep_image(scene: dict, project_dir: str) -> str:
    """이미지를 로컬에 보관하고 경로를 돌려준다. 실패하면 빈 문자열."""
    if is_usable(scene.get("image_local", "")):
        return scene["image_local"]
    url = scene.get("reference_image_url") or scene.get("image_path") or ""
    if not url:
        return ""
    if not url.startswith("http"):
        return url if is_usable(url) else ""
    ext = ".png" if ".png" in url.lower() else ".webp" if ".webp" in url.lower() else ".jpg"
    dest = os.path.join(_media_dir(project_dir), f"img_{int(scene.get('scene_no', 0)):02d}{ext}")
    if _download(url, dest):
        scene["image_local"] = dest
        return dest
    return ""


def keep_clip(scene: dict, project_dir: str) -> str:
    """영상 클립을 로컬에 보관하고 경로를 돌려준다. 실패하면 빈 문자열."""
    if is_usable(scene.get("video_local", "")):
        return scene["video_local"]
    url = scene.get("video_url", "")
    if not url.startswith("http"):
        return url if is_usable(url) else ""
    dest = os.path.join(_media_dir(project_dir), f"clip_{int(scene.get('scene_no', 0)):02d}.mp4")
    if _download(url, dest):
        scene["video_local"] = dest
        return dest
    return ""


def forget_image(scene: dict) -> None:
    """이미지를 새로 만들었을 때 예전 로컬 사본 연결을 끊는다."""
    scene.pop("image_local", None)


def forget_clip(scene: dict) -> None:
    scene.pop("video_local", None)
