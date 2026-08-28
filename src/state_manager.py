# src/state_manager.py
# 너도나도아는커피 숏폼 팩토리 — JSON 기반 프로젝트 상태 관리

import json
import os
from datetime import datetime


class StateManager:
    """
    프로젝트별 상태(state.json)를 생성·저장·불러오기·목록 조회한다.

    디렉터리 구조:
        projects/
        └── {timestamp}_{safe_topic}/
            ├── state.json         # 전체 상태 (씬 목록 포함)
            ├── narration.mp3      # ElevenLabs 음성 (STEP 2 완료 후)
            ├── scene_01.mp4       # Kling 영상 컷 (STEP 3 완료 후)
            ├── scene_02.mp4
            └── final.mp4          # 최종 합성 영상 (STEP 4 완료 후)
    """

    def __init__(self, storage_dir: str = "projects"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    # ── 새 프로젝트 생성 ──────────────────────────────────────────────────────
    def create_new_project(self, chapter: str, topic: str) -> dict:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = (
            "".join(c for c in topic if c.isalnum() or c in (" ", "_", "-"))
            .strip()
            .replace(" ", "_")
        )
        project_id = f"{timestamp}_{safe_topic}"
        project_dir = os.path.join(self.storage_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        state = {
            "project_id":       project_id,
            "project_dir":      project_dir,
            "created_at":       timestamp,
            "chapter":          chapter,
            "topic":            topic,
            "status":           "initialized",
            "full_narration":   "",
            "audio_path":       "",
            "scenes":           [],
            "final_video_path": "",
        }
        self.save_state(state)
        return state

    # ── 저장 ──────────────────────────────────────────────────────────────────
    def save_state(self, state: dict) -> str:
        state_path = os.path.join(state["project_dir"], "state.json")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return state_path

    # ── 불러오기 ──────────────────────────────────────────────────────────────
    def load_state(self, project_dir: str) -> dict:
        state_path = os.path.join(project_dir, "state.json")
        if not os.path.exists(state_path):
            raise FileNotFoundError(f"state.json 없음: {state_path}")
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── 프로젝트 목록 (최신순) ─────────────────────────────────────────────────
    def list_projects(self) -> list:
        if not os.path.exists(self.storage_dir):
            return []
        projects = []
        for d in sorted(os.listdir(self.storage_dir), reverse=True):
            p_dir = os.path.join(self.storage_dir, d)
            state_file = os.path.join(p_dir, "state.json")
            if os.path.isdir(p_dir) and os.path.exists(state_file):
                try:
                    state = self.load_state(p_dir)
                    projects.append({
                        "id":    state.get("project_id", d),
                        "title": (
                            f"[{state.get('chapter', '')}] "
                            f"{state.get('topic', d)} "
                            f"({state.get('status', '')})"
                        ),
                        "dir":   p_dir,
                    })
                except Exception:
                    continue
        return projects

    # ── 개별 씬 상태 업데이트 헬퍼 ────────────────────────────────────────────
    def update_scene(self, state: dict, scene_no: int, **kwargs) -> dict:
        """
        state["scenes"] 안에서 scene_no 에 해당하는 씬을 찾아 필드를 업데이트하고
        state.json 에 저장한 뒤 업데이트된 state 를 반환한다.

        사용 예:
            state = manager.update_scene(state, 3, status="done", video_url="/path/to/file.mp4")
        """
        for scene in state["scenes"]:
            if scene.get("scene_no") == scene_no:
                scene.update(kwargs)
                break
        self.save_state(state)
        return state
