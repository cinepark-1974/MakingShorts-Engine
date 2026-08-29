# src/assembler.py
# 너도나도아는커피 숏폼 팩토리 — FFmpeg 최종 합성기
#
# 동작 순서:
#   1. 씬별 video_url(CDN or 로컬) → /tmp 다운로드
#   2. FFmpeg concat → 하나의 MP4로 이어붙이기
#   3. 나레이션 MP3(CDN or 로컬) 오버레이
#   4. 최종 MP4 → fal.ai CDN 업로드 → URL 반환
#
# Whisper 자막은 향후 확장 예정 (현재 버전: 비디오 + 오디오 합성)

import os
import shutil
import subprocess
import tempfile
import requests
import fal_client


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def _download_to(url: str, dest_path: str, timeout: int = 180) -> bool:
    """URL에서 파일을 다운로드한다. 성공 시 True, 실패 시 False."""
    try:
        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        return os.path.getsize(dest_path) > 0
    except Exception:
        return False


def _copy_or_download(src: str, dest_path: str) -> bool:
    """
    src가 URL이면 다운로드, 로컬 파일이면 복사한다.
    성공 시 True 반환.
    """
    if src.startswith("http"):
        return _download_to(src, dest_path)
    if os.path.exists(src):
        shutil.copy2(src, dest_path)
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────
def assemble_final_video(state: dict, fal_key: str) -> str:
    """
    state의 모든 씬 video_url과 audio_path를 합쳐 최종 숏폼을 만들고
    fal.ai CDN URL을 반환한다.

    Args:
        state   : 프로젝트 상태 dict (scenes, audio_path 포함)
        fal_key : FAL_KEY (fal.ai 업로드용)

    Returns:
        str : 최종 영상 fal CDN URL (state["final_video_path"]에 저장)

    Raises:
        ValueError : 합성할 클립이 없거나 FFmpeg 실패 시
    """
    os.environ["FAL_KEY"] = fal_key

    scenes    = state.get("scenes", [])
    audio_src = state.get("audio_path", "").strip()

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── 1. 비디오 클립 다운로드 ─────────────────────────────────────────
        clip_paths = []
        for scene in sorted(scenes, key=lambda s: s.get("scene_no", 0)):
            video_src = scene.get("video_url", "").strip()
            if not video_src:
                continue
            sno       = scene.get("scene_no", 0)
            clip_path = os.path.join(tmpdir, f"clip_{sno:02d}.mp4")
            if _copy_or_download(video_src, clip_path):
                clip_paths.append(clip_path)

        if not clip_paths:
            raise ValueError(
                "합성할 영상 클립이 없습니다. "
                "STEP 4에서 모든 컷 영상을 먼저 생성해 주세요."
            )

        # ── 2. FFmpeg 클립 리스트 파일 ──────────────────────────────────────
        list_file = os.path.join(tmpdir, "clips.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for p in clip_paths:
                escaped = p.replace("\\", "\\\\").replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

        # ── 3. 클립 이어붙이기 ──────────────────────────────────────────────
        concat_path = os.path.join(tmpdir, "concat.mp4")
        proc = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                concat_path,
            ],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace")[-1000:]
            raise ValueError(f"FFmpeg concat 실패:\n{err}")

        # ── 4. 나레이션 오디오 준비 ─────────────────────────────────────────
        audio_path = ""
        if audio_src:
            audio_path = os.path.join(tmpdir, "narration.mp3")
            if not _copy_or_download(audio_src, audio_path):
                audio_path = ""   # 오디오 실패해도 영상 합성 계속

        # ── 5. 오디오 합성 ──────────────────────────────────────────────────
        final_path = os.path.join(tmpdir, "final.mp4")

        if audio_path and os.path.exists(audio_path):
            proc = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", concat_path,
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "128k",
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-shortest",
                    final_path,
                ],
                capture_output=True,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")[-1000:]
                raise ValueError(f"FFmpeg 오디오 합성 실패:\n{err}")
        else:
            shutil.copy2(concat_path, final_path)

        # ── 6. fal.ai CDN 업로드 ────────────────────────────────────────────
        with open(final_path, "rb") as f:
            video_bytes = f.read()

        cdn_url = fal_client.upload(video_bytes, content_type="video/mp4")
        return cdn_url
