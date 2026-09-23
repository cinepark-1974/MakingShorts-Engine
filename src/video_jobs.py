# src/video_jobs.py
# 너도나도아는커피 숏폼 팩토리 — 영상 생성 백그라운드 작업 관리자
#
# 왜 필요한가:
#   예전에는 영상 생성(컷당 2~3분)을 Streamlit 화면 실행 안에서 직접 돌렸다.
#   그 사이 버튼 클릭·브라우저 절전·연결 재접속으로 화면이 다시 실행되면
#   생성 작업이 조용히 끊기고, 화면에는 "영상 생성 중…"만 남은 채 멈춰 보였다.
#
#   이 모듈은 영상 생성을 별도 스레드(백그라운드)에서 돌리고,
#   컷별 진행 상태를 메모리에 기록한다. 화면은 몇 초마다 이 기록을 읽어 보여주기만 한다.
#   → 화면이 새로고침되거나 다시 실행돼도 생성 작업은 끊기지 않는다.
#
# 주의: 이 모듈 안에서는 st.* (Streamlit 함수)를 절대 호출하지 않는다.

import threading
import time

_JOBS: dict = {}            # project_id → job dict (서버 프로세스가 살아있는 동안 유지)
_LOCK = threading.Lock()

INTER_SCENE_SEC = 5         # 컷 사이 간격 (rate limit 예방)


def get_job(project_id: str):
    return _JOBS.get(project_id)


def is_running(project_id: str) -> bool:
    job = _JOBS.get(project_id)
    return bool(job and job["thread"].is_alive())


def request_stop(project_id: str) -> None:
    job = _JOBS.get(project_id)
    if job:
        job["stop"] = True


def start_job(project_id: str, state: dict, scene_nos: list,
              replicate_token: str, save_fn) -> bool:
    """
    영상 생성 작업을 백그라운드로 시작한다.
    이미 같은 프로젝트의 작업이 돌고 있으면 False를 반환하고 아무것도 하지 않는다.

    state     : 프로젝트 상태 dict (scenes 안의 각 컷 dict를 작업이 직접 갱신한다)
    scene_nos : 생성할 컷 번호 리스트 (순서대로 처리)
    save_fn   : save_fn(state) — 컷 하나 끝날 때마다 디스크에 저장
    """
    with _LOCK:
        if is_running(project_id):
            return False
        now = time.time()
        job = {
            "state":     state,
            "scene_nos": list(scene_nos),
            "progress":  {
                n: {"state": "queued", "started": None, "last_poll": None, "msg": ""}
                for n in scene_nos
            },
            "stop":       False,
            "error":      "",
            "started_at": now,
            "finished_at": None,
            "ui_sig":     None,   # 화면 갱신 판단용 (main.py에서 사용)
            "ui_done":    False,  # 완료 후 화면 최종 반영 여부
        }
        th = threading.Thread(
            target=_worker, args=(job, replicate_token, save_fn), daemon=True
        )
        job["thread"] = th
        _JOBS[project_id] = job
        th.start()
        return True


def _safe_save(save_fn, state):
    try:
        save_fn(state)
    except Exception as e:
        print(f"[video_jobs] 상태 저장 실패: {e}", flush=True)


def _worker(job: dict, replicate_token: str, save_fn) -> None:
    from src.video_replicate import generate_single_clip_url, InsufficientCreditError

    state = job["state"]
    smap  = {s["scene_no"]: s for s in state.get("scenes", [])}
    order = job["scene_nos"]

    try:
        for i, sno in enumerate(order):
            p = job["progress"][sno]
            scene = smap.get(sno)

            if job["stop"]:
                p["state"] = "skipped"
                continue
            if scene is None:
                p["state"], p["msg"] = "error", "씬을 찾을 수 없습니다."
                continue

            if i > 0:
                time.sleep(INTER_SCENE_SEC)

            p["state"]   = "generating"
            p["started"] = time.time()
            scene["status"] = "generating"

            def _poll_cb(elapsed, _p=p):
                _p["last_poll"] = time.time()

            try:
                url = generate_single_clip_url(
                    replicate_token=replicate_token,
                    prompt=scene.get("flow_prompt", ""),
                    image_url=scene.get("reference_image_url", ""),
                    poll_cb=_poll_cb,
                )
                scene["video_url"] = url
                scene["status"]    = "done"
                scene.pop("error_msg", None)
                p["state"] = "done"

            except InsufficientCreditError as e:
                # 크레딧 부족 → 이 컷은 '대기'로 되돌리고 남은 컷은 건너뜀
                scene["status"] = "pending"
                p["state"], p["msg"] = "error", str(e)
                job["error"] = str(e)
                for rest in order[i + 1:]:
                    job["progress"][rest]["state"] = "skipped"
                _safe_save(save_fn, state)
                break

            except Exception as e:
                scene["status"]    = "error"
                scene["error_msg"] = str(e)
                p["state"], p["msg"] = "error", str(e)

            p["finished"] = time.time()
            _safe_save(save_fn, state)   # 컷 하나 끝날 때마다 저장

    except BaseException as e:            # 예상 못한 오류도 기록
        job["error"] = f"작업 중단: {e}"
        print(f"[video_jobs] 작업 오류: {e}", flush=True)

    finally:
        # 끝났는데 '생성중'으로 남은 컷은 '대기'로 되돌려 다음에 다시 생성되게 한다
        for sno in order:
            sc = smap.get(sno)
            if sc is not None and sc.get("status") == "generating":
                sc["status"] = "pending"
        _safe_save(save_fn, state)
        job["finished_at"] = time.time()
