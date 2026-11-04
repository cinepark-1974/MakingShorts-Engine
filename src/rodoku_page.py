# src/rodoku_page.py
# SceneStory 朗読ドラマ 화면 — 버튼 한 번으로 자동 제작, 작가는 확인 후 업로드만.

import os

from src import hasira as hz
from src import rodoku as R
from src.hasira_page import _job_panel

NEED_KEYS = ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "REPLICATE_API_TOKEN"]


def render_new(st, manager, api_keys):
    st.markdown(
        "**📖 朗読ドラマ 자동 제작** — 일본 YouTube 검색어(시니어 연애·인생)를 조회해 소재를 고르고, "
        "오리지널 단편을 일본어로 써서 낭독·그림·16:9 영상·예고 쇼츠·섬네일·업로드 정보까지 만듭니다. "
        "작가님은 완성본을 확인하고 올리기만 하면 됩니다."
    )
    c1, c2 = st.columns([2, 3])
    with c1:
        minutes = st.radio("길이", list(R.LENGTHS), format_func=lambda k: R.LENGTHS[k]["label"],
                           index=list(R.LENGTHS).index(R.DEFAULT_MIN), horizontal=True, key="rd_minutes")
    with c2:
        st.caption("걸리는 시간 약 15~25분 (집필·낭독·그림·합성). 화면을 닫아도 서버에서 계속 진행됩니다. "
                   "비용: Claude 집필 + ElevenLabs 일본어 낭독(약 4천~5천 자) + Replicate 그림 5~6장 + "
                   "이 편 전용 배경음악 2곡(반전 전·후 각 3분, 음악 약 6분).")
    motion_on = st.toggle("🎞 움직이는 그림 (장마다 MiniMax 6초 클립 → 초당 7.5장 손그림 애니메이션 느낌으로 반복)",
                          value=True, key="rd_motion",
                          help="끄면 그림을 천천히 확대·축소(Ken Burns)만 합니다. 켜면 Replicate 영상 비용이 장 수만큼 추가되고 "
                               "제작 시간이 10~20분 늘어납니다. 실패한 장은 자동으로 Ken Burns 로 대신합니다.")
    miss = [k for k in NEED_KEYS if not str(api_keys.get(k, "")).strip()]
    if miss:
        st.error("Secrets 에 없는 키: " + ", ".join(miss))
    if st.button("🤖 자동 제작 시작", type="primary", use_container_width=True, disabled=bool(miss), key="rd_start"):
        state = manager.create_new_project(chapter="朗読ドラマ", topic="朗読ドラマ 자동", channel="scenestory")
        state.update(mode="rodoku", minutes=int(minutes), title="朗読ドラマ (자동 제작 중)", stage="queued",
                     motion_on=bool(motion_on))
        manager.save_state(state)
        made = [p["title"] for p in manager.list_projects() if p.get("channel") == "scenestory"]
        R.start_auto(state, api_keys, manager.save_state, made)
        st.session_state.current_project = state
        st.rerun()
    _recover(st, manager, api_keys)
    with st.expander("지금 일본에서 찾는 검색어 미리 보기 (선택)"):
        if st.button("🔎 검색어 조회", key="rd_peek"):
            with st.spinner("일본 YouTube 자동완성 조회 중…"):
                st.session_state["_rd_peek"] = R.collect_trends()
        pk = st.session_state.get("_rd_peek")
        if pk:
            st.caption("씨앗: " + ", ".join(pk["seeds"]))
            st.write(" · ".join(pk["queries"]) or "받아온 검색어가 없습니다.")


def _recover(st, manager, api_keys):
    """서버 재시작으로 목록에서 사라진 작업을 R2 에 남은 상태로 되살린다."""
    idx = R.cloud_index(api_keys)
    if not idx:
        return
    local = {p.get("id") for p in manager.list_projects()}
    lost = [(pid, row) for pid, row in sorted(idx.items(), reverse=True) if pid not in local][:8]
    if not lost:
        return
    with st.container(border=True):
        st.markdown("**↩ 서버 재시작으로 목록에서 사라진 작업** — 클라우드(R2)에 저장된 진행 상태로 되살립니다. "
                    "끝난 단계(원고·그림·낭독 등)는 다시 만들지 않습니다.")
        for pid, row in lost:
            c1, c2 = st.columns([3, 1])
            c1.caption(f"{row.get('title', '')} · 마지막 단계: {dict(R.STAGES).get(row.get('stage', ''), row.get('stage', ''))} · {row.get('at', '')}")
            if c2.button("되살리기", key=f"rd_rec_{pid}", use_container_width=True):
                state = R.cloud_state(api_keys, pid)
                if not state:
                    st.error("R2 에서 상태를 찾지 못했습니다.")
                    return
                manager.save_state(state)
                st.session_state.current_project = state
                st.rerun()


def _dl(st, keys, item, label, key, mime):
    link = R.link(keys, item)
    if link:
        st.link_button(label + " (R2 · 7일)", link, use_container_width=True)
    elif hz.usable(item.get("local", "")) and os.path.getsize(item["local"]) < 200_000_000:
        with open(item["local"], "rb") as f:
            st.download_button(label, f.read(), file_name=os.path.basename(item["local"]), mime=mime, key=key,
                               use_container_width=True)


def render_project(st, manager, api_keys, show_banner):
    show_banner("scenestory")
    state = st.session_state.current_project
    pid = state["project_id"]
    plan = state.get("plan") or {}
    running = hz.is_running(pid)

    st.markdown(f"### {plan.get('title_ja') or state.get('title', '')}")
    if plan.get("title_ko"):
        st.caption(f"{plan['title_ko']} · {plan.get('logline_ko', '')}")
    _job_panel(st, state, "top")

    # 단계 표시
    cur = state.get("stage", "")
    keys_order = [k for k, _ in R.STAGES]
    done_idx = len(keys_order) if cur == "done" else (keys_order.index(cur) if cur in keys_order else -1)
    st.markdown("  ".join(("✅ " if i < done_idx else ("⏳ " if i == done_idx and running else "▫️ ")) + lab
                          for i, (_, lab) in enumerate(R.STAGES)))
    if cur != "done" and not running:
        b1, b2 = st.columns(2)
        with b1:
            if st.button("▶ 이어서 만들기 (끝난 단계는 건너뜀)", type="primary", use_container_width=True, key="rd_resume"):
                made = [p["title"] for p in manager.list_projects() if p.get("channel") == "scenestory"
                        and p.get("id") != pid]
                R.start_auto(state, api_keys, manager.save_state, made)
                st.rerun()
        with b2:
            st.caption("오류로 멈췄거나 서버가 재시작됐다면 이어서 만들기를 누르세요. 끝난 단계는 다시 하지 않습니다.")
    chs0 = state.get("chapters") or []
    if not running and any((c.get("image") or {}).get("local") or (c.get("image") or {}).get("r2_key") for c in chs0):
        with st.expander("🎨 그림만 새 그림체로 다시 그리기"):
            st.caption("장별 그림을 지우고 새로 그립니다. 원고·낭독·배경음악은 그대로 두고, 합성·예고편·섬네일은 새 그림으로 다시 만듭니다. "
                       f"Replicate 그림 {len(chs0)}장 비용이 다시 듭니다.")
            if st.button("그림 다시 그리고 이어서 만들기", key="rd_redraw", use_container_width=True):
                for c in chs0:
                    c["image"] = {}
                    c["motion"] = {}
                for k in ("final", "trailer", "thumbnail", "upload_pack"):
                    state.pop(k, None)
                state["stage"] = "images"
                import shutil
                shutil.rmtree(os.path.dirname(R.pf(state, "work", "x")), ignore_errors=True)   # 예전 그림의 화면 루프
                manager.save_state(state)
                made = [p["title"] for p in manager.list_projects() if p.get("channel") == "scenestory"
                        and p.get("id") != pid]
                R.start_auto(state, api_keys, manager.save_state, made)
                st.rerun()

    tr = state.get("trend") or {}
    if plan:
        with st.container(border=True):
            st.markdown("**소재 · 설계**")
            if plan.get("kind"):
                st.markdown(f"이야기 종류 · **{plan['kind']}** (최근 6편과 겹치지 않게 엔진이 고름)")
            st.markdown(f"고른 검색어 · `{plan.get('picked_query', '')}` — {plan.get('why_ko', '')}")
            if tr.get("queries"):
                st.caption("조회한 검색어 · " + " · ".join(tr["queries"][:20]) + (" (기본 검색어 사용)" if tr.get("fallback") else ""))
            stg = plan.get("setting") or {}
            st.markdown(f"무대 · {stg.get('place', '')} / {stg.get('time', '')} · 소품 · {stg.get('object', '')}")
            for ch in plan.get("characters") or []:
                st.caption(f"{ch.get('name', '')} ({ch.get('age', '')}) · {ch.get('role', '')} · 비밀: {ch.get('secret', '')}")
            if plan.get("turn"):
                st.caption(f"반전 · {plan['turn']}")

    chs = state.get("chapters") or []
    if chs:
        with st.container(border=True):
            st.markdown(f"**원고** · {state.get('manuscript_chars', 0)}자")
            for c in chs:
                lab = f"第{c['no']}章 「{c.get('title_ja', '')}」 · {c.get('beat_ko', '')}"
                with st.expander(lab + (f" · {c.get('chars', 0)}자" if c.get("text") else " · 아직")):
                    img = hz.ensure_local(api_keys, c.get("image") or {}, R.pf(state, f"ch{c['no']:02d}.jpg")) if c.get("image") else ""
                    if img:
                        st.image(img, use_container_width=True)
                    mo = c.get("motion") or {}
                    if mo.get("error"):
                        st.caption(f"움직임 실패 → Ken Burns 로 대신: {mo['error'][:150]}")
                    elif mo.get("local") or mo.get("r2_key"):
                        mv = hz.ensure_local(api_keys, mo, R.pf(state, f"ch{c['no']:02d}_motion.mp4"))
                        if mv:
                            st.video(mv)
                            st.caption("움직임 원본 6초 (합성 때 초당 7.5장으로 줄여 앞뒤로 반복)")
                    if c.get("text"):
                        st.text(c["text"])
                    au = c.get("audio") or {}
                    if hz.usable(au.get("local", "")):
                        st.audio(au["local"])
                        st.caption(f"낭독 {au.get('seconds', 0)}초 · {au.get('model', '')}")

    bgm = state.get("bgm") or {}
    if bgm:
        with st.container(border=True):
            st.markdown(f"**배경음악 (이 편 전용)** · 第{plan.get('turn_chapter', '?')}章 제목 카드에서 곡이 바뀝니다")
            for kind, lab in (("a", "반전 전"), ("b", "반전 후")):
                it = bgm.get(kind) or {}
                loc = hz.ensure_local(api_keys, it, R.pf(state, "music", f"bgm_{kind}.mp3")) if (it.get("local") or it.get("r2_key")) else ""
                if loc:
                    st.audio(loc)
                    st.caption(f"{lab} · {it.get('seconds', 0)}초 · {it.get('prompt', '')[:160]}")
                elif it.get("error"):
                    st.warning(f"{lab} 곡을 만들지 못했습니다 (이 곡 없이 합성): {it['error']}")

    fin = state.get("final") or {}
    if fin.get("seconds"):
        with st.container(border=True):
            st.markdown(f"**본편 (16:9)** · {hz.fmt_time(fin['seconds'], True)} · {fin.get('bytes', 0) / 1e6:.0f}MB · {fin.get('made_at', '')}")
            _dl(st, api_keys, fin, "⬇ 본편 내려받기", "rd_fin", "video/mp4")
            th = state.get("thumbnail") or {}
            if hz.usable(th.get("local", "")):
                st.image(th["local"], caption="섬네일 1280×720", use_container_width=True)
                _dl(st, api_keys, th, "⬇ 섬네일 내려받기", "rd_th", "image/jpeg")

    trl = state.get("trailer") or {}
    if trl.get("local") or trl.get("error"):
        with st.container(border=True):
            st.markdown("**예고 쇼츠 (9:16)**")
            if trl.get("error"):
                st.warning(f"예고편을 만들지 못했습니다: {trl['error']}")
            else:
                if hz.usable(trl["local"]):
                    st.video(trl["local"])
                st.caption(f"{trl.get('seconds', 0)}초 · 第{trl.get('chapter', '')}章에서 · 쇼츠 제목: {trl.get('shorts_title', '')}")
                _dl(st, api_keys, trl, "⬇ 예고 쇼츠 내려받기", "rd_tr", "video/mp4")

    pack = state.get("upload_pack")
    if pack:
        with st.container(border=True):
            st.markdown("**업로드 정보 (일본어)**")
            st.markdown("제목")
            st.code(pack.get("title", ""), language=None)
            st.markdown("설명")
            st.code(pack.get("full_description", ""), language=None)
            st.markdown("태그")
            st.code(", ".join(pack.get("tags", [])), language=None)
            if trl.get("shorts_title"):
                st.markdown("예고 쇼츠 제목")
                st.code(trl["shorts_title"], language=None)
            for k, v in R.UPLOAD_SETTINGS:
                st.caption(f"{k} · {v}")
