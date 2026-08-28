# src/assembler.py
# 너도나도아는커피 숏폼 팩토리 — FFmpeg + Whisper 최종 합성기
#
# ──────────────────────────────────────────────────────────────────────────────
# [구현 대기 중]
#
# STEP 3 영상 컷 전체 + STEP 2 나레이션 음성이 완료된 뒤 실행한다.
# Streamlit Cloud 환경에서 FFmpeg 실행 가능 여부와
# openai-whisper 의 Streamlit Cloud 메모리 한도(1GB) 적합성을
# 실제 테스트로 먼저 확인한 뒤 아래 TODO 구간을 채워야 합니다.
#
# 합성 순서 (예상):
#   1. 12개 scene_XX.mp4 를 FFmpeg concat 으로 하나의 무음 영상으로 이어 붙임
#   2. narration.mp3 를 오버레이 (aac 인코딩)
#   3. assets/sfx/ 효과음을 씬별 타임코드에 믹싱
#   4. Whisper 로 narration.mp3 → SRT 자막 생성
#   5. FFmpeg subtitles 필터로 자막 번인
#   6. 최종 final.mp4 저장
#
# 확인이 필요한 항목:
#   1. Streamlit Cloud 에서 subprocess / ffmpeg-python 실행 허용 여부
#   2. Whisper 모델 크기 (tiny / base) — Cloud 메모리 제약 고려
#   3. SFX 타임코드 계산 방식 (씬 번호 × 5초 고정 vs 음성 길이 기반 동적)
#   4. 자막 스타일 (폰트, 크기, 위치, 다이나믹 하이라이트 여부)
# ──────────────────────────────────────────────────────────────────────────────

import os


def assemble_final_video(
    state: dict,
    bgm_path: str = "",
    subtitle_style: str = "default",
) -> str:
    """
    모든 컷 영상 + 나레이션 음성 + SFX + BGM을 합쳐 최종 숏폼 MP4를 생성한다.

    Args:
        state          : StateManager 가 관리하는 프로젝트 상태 딕셔너리
        bgm_path       : 배경음악 파일 경로 (없으면 빈 문자열)
        subtitle_style : 자막 스타일 식별자 ("default" | "dynamic")

    Returns:
        str : 저장된 final.mp4 의 로컬 경로

    Raises:
        NotImplementedError : 아직 구현되지 않은 상태
        FileNotFoundError   : 음성 파일 또는 영상 컷 파일 누락 시
    """
    # ── 사전 조건 검증 ────────────────────────────────────────────────────────
    audio_path  = state.get("audio_path", "")
    project_dir = state.get("project_dir", "")
    scenes      = state.get("scenes", [])

    if not audio_path or not os.path.exists(audio_path):
        raise FileNotFoundError(f"나레이션 음성 파일 없음: {audio_path}")

    missing_clips = [
        s["scene_no"]
        for s in scenes
        if s.get("status") != "done" or not os.path.exists(s.get("video_url", ""))
    ]
    if missing_clips:
        raise FileNotFoundError(f"영상 미완료 씬: {missing_clips}")

    # ── 구현 전 가드 ──────────────────────────────────────────────────────────
    raise NotImplementedError(
        "src/assembler.py 는 아직 구현되지 않았습니다.\n"
        "FFmpeg·Whisper 실행 환경 테스트 후 이 함수를 완성하세요."
    )

    # ── TODO: 아래 단계를 순서대로 구현 ──────────────────────────────────────
    #
    # [1] 씬 영상 concat 리스트 파일 생성
    # concat_list_path = os.path.join(project_dir, "concat.txt")
    # with open(concat_list_path, "w") as f:
    #     for scene in sorted(scenes, key=lambda s: s["scene_no"]):
    #         f.write(f"file '{os.path.abspath(scene['video_url'])}'\n")
    #
    # [2] FFmpeg concat → 무음 합본
    # import ffmpeg
    # raw_video = os.path.join(project_dir, "raw_concat.mp4")
    # (
    #     ffmpeg
    #     .input(concat_list_path, format="concat", safe=0)
    #     .output(raw_video, c="copy")
    #     .overwrite_output()
    #     .run()
    # )
    #
    # [3] 나레이션 오버레이
    # with_audio = os.path.join(project_dir, "with_audio.mp4")
    # video_in = ffmpeg.input(raw_video)
    # audio_in = ffmpeg.input(audio_path)
    # (
    #     ffmpeg
    #     .output(video_in, audio_in, with_audio, vcodec="copy", acodec="aac", shortest=None)
    #     .overwrite_output()
    #     .run()
    # )
    #
    # [4] Whisper → SRT 자막 생성
    # import whisper
    # whisper_model = whisper.load_model("base")
    # result = whisper_model.transcribe(audio_path, language="ko")
    # srt_path = os.path.join(project_dir, "narration.srt")
    # # SRT 포맷 변환 함수 작성 필요
    #
    # [5] FFmpeg 자막 번인
    # final_path = os.path.join(project_dir, "final.mp4")
    # (
    #     ffmpeg
    #     .input(with_audio)
    #     .output(final_path, vf=f"subtitles={srt_path}")
    #     .overwrite_output()
    #     .run()
    # )
    #
    # return final_path
