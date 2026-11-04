# src/rodoku_page.py
# SceneStory 朗読ドラマ 화면 — 버튼 한 번으로 자동 제작, 작가는 확인 후 업로드만.

import os

from src import hasira as hz
from src import rodoku as R
from src.hasira_page import _job_panel
from src.naming import out_name

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
    _comp_new(st, manager, api_keys)
    with st.expander("지금 일본에서 찾는 검색어 미리 보기 (선택)"):
        if st.button("🔎 검색어 조회", key="rd_peek"):
            with st.spinner("일본 YouTube 자동완성 조회 중…"):
                st.session_state["_rd_peek"] = R.collect_trends()
        pk = st.session_state.get("_rd_peek")
        if pk:
            st.caption("씨앗: " + ", ".join(pk["seeds"]))
            st.write(" · ".join(pk["queries"]) or "받아온 검색어가 없습니다.")


def _comp_new(st, manager, api_keys):
    """📚 모음편 (약 1시간) — 이미 만든 본편 3~4편을 이어 붙인다."""
    from src import rodoku_comp as C
    with st.expander("📚 모음편 만들기 (본편 3~4편 → 약 1시간) · 본편 시청 시간 늘리기"):
        st.caption("이미 만든 편을 이어 붙여 한 편으로 냅니다. 새로 만드는 비용은 섬네일·업로드 정보뿐입니다. "
                   "본편 파일이 지워졌으면 R2 의 본편 → R2 의 재료로 다시 합성 → 직접 올린 mp4 순서로 찾습니다.")
        if st.button("편 목록 불러오기", key="rdc_load"):
            with st.spinner("서버·R2 에서 완성된 편을 찾는 중…"):
                st.session_state["_rdc_eps"] = C.episodes(manager, api_keys)
        eps = st.session_state.get("_rdc_eps")
        if eps is None:
            return
        if not eps:
            st.info("완성된 朗読ドラマ 편을 찾지 못했습니다.")
            return
        ups = st.session_state.setdefault("_rdc_uploads", {})
        picked = []
        for ep in eps:
            pid = ep["project_id"]
            plan = ep.get("plan") or {}
            src = C.source_of(api_keys, ep, ups)
            c1, c2 = st.columns([3, 2])
            on = c1.checkbox(f"{plan.get('title_ja', pid)} · {hz.fmt_time((ep.get('final') or {}).get('seconds', 0), True)}",
                             key=f"rdc_pick_{pid}", value=False)
            c2.caption(("✅ " if src != "none" else "⚠️ ") + C.SOURCE_LABEL[src])
            if src == "none":
                up = st.file_uploader(f"『{plan.get('title_ja', pid)}』 본편 mp4 올리기", type=["mp4"], key=f"rdc_up_{pid}")
                if up is not None:
                    d = os.path.join("projects", "_uploads")
                    os.makedirs(d, exist_ok=True)
                    path = os.path.join(d, f"{pid}.mp4")
                    with open(path, "wb") as f:
                        f.write(up.getbuffer())
                    ups[pid] = path
                    st.rerun()
            if on:
                picked.append(ep)
        n_ok = sum(1 for ep in picked if C.source_of(api_keys, ep, ups) != "none")
        tot = sum((ep.get("final") or {}).get("seconds", 0) for ep in picked)
        st.caption(f"고른 편 {len(picked)}개 · 사용 가능 {n_ok}개 · 합계 약 {hz.fmt_time(tot, True)} (편마다 제목 카드 5초 추가)")
        if st.button("📚 모음편 만들기", type="primary", disabled=n_ok < 2, key="rdc_start", use_container_width=True):
            state = manager.create_new_project(chapter="朗読ドラマ", topic="모음편", channel="scenestory")
            state.update(mode="rodoku_comp", title="모음편 (만드는 중)", stage="queued", uploads=dict(ups),
                         comp={"episodes": [{"pid": ep["project_id"], "title": (ep.get("plan") or {}).get("title_ja", ""),
                                             "state": ep} for ep in sorted(picked, key=lambda s: s["project_id"])]})
            manager.save_state(state)
            C.start(state, api_keys, manager.save_state)
            st.session_state.current_project = state
            st.rerun()


def render_comp_project(st, manager, api_keys, show_banner):
    from src import rodoku_comp as C
    show_banner("scenestory")
    state = st.session_state.current_project
    pid = state["project_id"]
    st.markdown(f"### 📚 {state.get('title', '모음편')}")
    st.caption("수록: " + " / ".join(e["title"] for e in (state.get("comp") or {}).get("episodes", [])))
    _job_panel(st, state, "top")
    fin = state.get("final") or {}
    if not fin.get("seconds") and not hz.is_running(pid):
        if st.button("▶ 다시 만들기", type="primary", key="rdc_retry"):
            C.start(state, api_keys, manager.save_state)
            st.rerun()
    if fin.get("seconds"):
        with st.container(border=True):
            st.markdown(f"**모음편 (16:9)** · {hz.fmt_time(fin['seconds'], True)} · {fin.get('bytes', 0) / 1e6:.0f}MB")
            for sk in fin.get("skipped") or []:
                st.warning("건너뛴 편 · " + sk)
            _dl(st, api_keys, fin, "⬇ 모음편 내려받기", "rdc_fin", "video/mp4", out_name(state, "compilation", "mp4"))
            th = state.get("thumbnail") or {}
            if hz.usable(th.get("local", "")):
                st.image(th["local"], caption="섬네일 1280×720", use_container_width=True)
                _dl(st, api_keys, th, "⬇ 섬네일 내려받기", "rdc_th", "image/jpeg", out_name(state, "thumbnail", "jpg"))
    pack = state.get("upload_pack")
    if pack:
        with st.container(border=True):
            st.markdown("**업로드 정보 (일본어)**")
            for lab, key in (("제목", "title"), ("설명", "full_description"), ("고정 댓글", "pinned_comment")):
                st.markdown(lab)
                st.code(pack.get(key, ""), language=None)
            st.markdown("태그")
            st.code(", ".join(pack.get("tags", [])), language=None)


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


def _dl(st, keys, item, label, key, mime, filename=""):
    link = R.link(keys, item, filename)
    if link:
        st.link_button(label + " (R2 · 7일)", link, use_container_width=True)
    elif hz.usable(item.get("local", "")) and os.path.getsize(item["local"]) < 200_000_000:
        with open(item["local"], "rb") as f:
            st.download_button(label, f.read(), file_name=filename or os.path.basename(item["local"]), mime=mime, key=key,
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
            yw = plan.get("young_woman") or {}
            if yw.get("role"):
                st.caption(f"젊은 여성 · {yw.get('name', '')} ({yw.get('age', '')}) · {yw.get('role', '')} · {yw.get('look_en', '')}")
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
                        rv = (c.get("image") or {}).get("review") or {}
                        if rv.get("problems"):
                            st.caption(f"그림 검수 ({c['image'].get('tries', 1)}장 중 가장 나은 것) · 남은 문제: " + " / ".join(rv["problems"]))
                        elif rv:
                            st.caption(f"그림 검수 통과 · {c['image'].get('tries', 1)}장째" + (" (검수 건너뜀)" if rv.get("skipped") else ""))
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
            _dl(st, api_keys, fin, "⬇ 본편 내려받기", "rd_fin", "video/mp4", out_name(state, "main", "mp4"))
            thumbs = state.get("thumbnails") or ([state["thumbnail"]] if (state.get("thumbnail") or {}).get("local") else [])
            if thumbs:
                st.caption("섬네일 3종 — YouTube 스튜디오(PC) → 동영상 세부정보 → 미리보기 이미지 → '테스트 및 비교'에 셋 다 올리면 "
                           "YouTube 가 더 많이 눌리는 쪽을 골라 줍니다.")
                cols = st.columns(len(thumbs))
                for col, t in zip(cols, thumbs):
                    with col:
                        tl = hz.ensure_local(api_keys, t, t.get("local") or R.pf(state, f"thumbnail_{t.get('tag', 'A')}.jpg")) \
                            if (t.get("local") or t.get("r2_key")) else ""
                        if tl:
                            st.image(tl, caption=f"{t.get('tag', '')} · {t.get('label', '')}", use_container_width=True)
                            _dl(st, api_keys, t, f"⬇ {t.get('tag', '')}", f"rd_th{t.get('tag', '')}", "image/jpeg",
                                out_name(state, f"thumbnail-{t.get('tag', 'A')}", "jpg"))
                        elif t.get("error"):
                            st.caption(f"{t.get('tag', '')} 실패: {t['error'][:100]}")

    shorts = [state.get("trailer") or {}] + list(state.get("trailers") or [])
    for k, it in enumerate(shorts):
        if not (it.get("local") or it.get("r2_key") or it.get("error")):
            continue
        folder = "trailer" if k == 0 else f"trailer{k + 1}"
        suf = "" if k == 0 else f"{k + 1}"
        with st.container(border=True):
            st.markdown(f"**예고 쇼츠 {k + 1} (9:16)**" + (f" · 올릴 날: {it['post_day']}" if it.get("post_day") else ""))
            if it.get("error"):
                st.warning(f"예고 쇼츠 {k + 1} 을(를) 만들지 못했습니다: {it['error']}")
                continue
            loc = hz.ensure_local(api_keys, it, R.pf(state, folder, "trailer.mp4"))
            if loc:
                st.video(loc)
            st.caption(f"{it.get('seconds', 0)}초 · 第{it.get('chapter', '')}章에서")
            _dl(st, api_keys, it, f"⬇ 예고 쇼츠 {k + 1} 내려받기", f"rd_tr{k}", "video/mp4", out_name(state, f"trailer{suf}", "mp4"))
            cv = it.get("cover") or {}
            cvl = hz.ensure_local(api_keys, cv, R.pf(state, folder, "cover_1080x1920.jpg")) if (cv.get("local") or cv.get("r2_key")) else ""
            if cvl:
                c1, c2 = st.columns([1, 2])
                c1.image(cvl, caption="쇼츠 표지 1080×1920")
                with c2:
                    _dl(st, api_keys, cv, "⬇ 쇼츠 표지 내려받기", f"rd_cv{k}", "image/jpeg", out_name(state, f"trailer{suf}-cover", "jpg"))
                    st.caption("YouTube 스튜디오(PC) → 콘텐츠 → Shorts → 연필 아이콘 → 미리보기 이미지")
            elif cv.get("error"):
                st.caption(f"쇼츠 표지를 만들지 못했습니다: {cv['error'][:150]}")
            for lab, key in (("쇼츠 제목", "shorts_title"), ("쇼츠 설명", "description"), ("쇼츠 고정 댓글", "comment")):
                if it.get(key):
                    st.markdown(lab)
                    st.code(it[key], language=None)

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
            if pack.get("pinned_comment"):
                st.markdown("본편 고정 댓글")
                st.code(pack["pinned_comment"], language=None)
            for k, v in R.UPLOAD_SETTINGS:
                st.caption(f"{k} · {v}")
