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
                   "비용: Claude 집필 + ElevenLabs 일본어 낭독(약 4천~5천 자) + Replicate 그림 5~6장 + 배경음악 1곡(처음 한 번).")
    miss = [k for k in NEED_KEYS if not str(api_keys.get(k, "")).strip()]
    if miss:
        st.error("Secrets 에 없는 키: " + ", ".join(miss))
    if st.button("🤖 자동 제작 시작", type="primary", use_container_width=True, disabled=bool(miss), key="rd_start"):
        state = manager.create_new_project(chapter="朗読ドラマ", topic="朗読ドラマ 자동", channel="scenestory")
        state.update(mode="rodoku", minutes=int(minutes), title="朗読ドラマ (자동 제작 중)", stage="queued")
        manager.save_state(state)
        made = [p["title"] for p in manager.list_projects() if p.get("channel") == "scenestory"]
        R.start_auto(state, api_keys, manager.save_state, made)
        st.session_state.current_project = state
        st.rerun()
    with st.expander("지금 일본에서 찾는 검색어 미리 보기 (선택)"):
        if st.button("🔎 검색어 조회", key="rd_peek"):
            with st.spinner("일본 YouTube 자동완성 조회 중…"):
                st.session_state["_rd_peek"] = R.collect_trends()
        pk = st.session_state.get("_rd_peek")
        if pk:
            st.caption("씨앗: " + ", ".join(pk["seeds"]))
            st.write(" · ".join(pk["queries"]) or "받아온 검색어가 없습니다.")


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
            st.caption("오류로 멈췄다면 위 상자의 이유를 확인한 뒤 이어서 만들기를 누르세요.")

    tr = state.get("trend") or {}
    if plan:
        with st.container(border=True):
            st.markdown("**소재 · 설계**")
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
                    if c.get("text"):
                        st.text(c["text"])
                    au = c.get("audio") or {}
                    if hz.usable(au.get("local", "")):
                        st.audio(au["local"])
                        st.caption(f"낭독 {au.get('seconds', 0)}초 · {au.get('model', '')}")

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
