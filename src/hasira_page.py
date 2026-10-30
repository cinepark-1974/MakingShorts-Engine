# src/hasira_page.py
# HASIRA_yo! 제작 화면 — main.py 에서 render() 한 번만 부른다.

import os
import time

from src import hasira as h


def _keys_missing(api_keys: dict, names) -> list:
    return [k for k in names if not str(api_keys.get(k, "")).strip()]


# ─────────────────────────────────────────────────────────────────────────────
# 새 프로젝트
# ─────────────────────────────────────────────────────────────────────────────
def _new_project(st, manager, api_keys):
    st.markdown(
        '<p style="text-align:center; font-size:14px; margin:4px 0 18px;">'
        '키워드 하나로 그림 · 움직임 · 곡 목록을 기획하고, 1시간 안팎의 16:9 음악 영상을 만듭니다.</p>',
        unsafe_allow_html=True,
    )
    with st.form("hz_new", border=True):
        kw = st.text_input("① 키워드 (분위기·장소·장르)", key="hz_kw",
                           placeholder="예: 비 오는 밤 교토 카페 재즈 피아노 / 벚꽃 길 어쿠스틱 기타 / 겨울 산장 난로 로파이")
        c1, c2 = st.columns(2)
        with c1:
            target = st.selectbox("영상 길이", list(h.LENGTH_OPTIONS), index=1,
                                  format_func=lambda k: h.LENGTH_OPTIONS[k], key="hz_target")
            provider = st.radio("음악 만드는 방법", list(h.PROVIDERS), format_func=lambda k: h.PROVIDERS[k],
                                key="hz_provider")
        with c2:
            track_min = st.select_slider("곡 하나 길이", options=[2, 3, 4, 5], value=3,
                                         format_func=lambda m: f"{m}분", key="hz_track_min")
            n_default = h.default_track_count(target, track_min)
            n_tracks = st.number_input("새로 만들 곡 수", min_value=3, max_value=40, value=n_default, step=1,
                                       key=f"hz_n_{target}_{track_min}",
                                       help="영상 길이보다 곡이 적으면 곡 목록을 처음부터 반복해 길이를 채웁니다.")
            visual = st.radio("화면", list(h.VISUAL_MODES), format_func=lambda k: h.VISUAL_MODES[k], key="hz_visual")
        if provider == "elevenlabs":
            st.caption(f"예상 음악 비용: {n_tracks}곡 × {track_min}분 × $0.15 ≈ "
                       f"${n_tracks * track_min * h.EL_PRICE_PER_MIN:.2f} (ElevenLabs 공식 API 요금 기준)")
        elif provider == "lyria":
            st.caption("Lyria 3.5 는 곡당 약 2분입니다. 요금은 Google 요금 문서에서 확인되지 않았습니다.")
        else:
            st.caption("Suno 는 공식 공개 API 가 없어 자동 연결하지 않습니다. Suno 웹에서 만든 MP3 를 "
                       "프로젝트 화면 ④ 단계에서 올리면 파일 이름이 곡 제목이 됩니다.")
        go = st.form_submit_button("🎼 기획 만들기", type="primary", use_container_width=True)

    if go:
        if not kw.strip():
            st.error("키워드를 입력해 주세요.")
            return
        if _keys_missing(api_keys, ["ANTHROPIC_API_KEY"]):
            st.error("ANTHROPIC_API_KEY 가 없습니다.")
            return
        with st.spinner("Claude 가 제목 · 그림 · 움직임 · 곡 목록을 기획하는 중… (약 30초)"):
            try:
                plan = h.make_plan(api_keys["ANTHROPIC_API_KEY"], kw, int(n_tracks), int(target))
            except Exception as e:
                st.error(f"기획 실패: {e}")
                return
        state = manager.create_new_project(chapter="HASIRA", topic=kw.strip(), channel="hasira")
        state.update(
            title=plan.get("title_ja") or kw.strip(), plan=plan, keyword=kw.strip(),
            target_min=int(target), track_sec=int(track_min) * 60, provider=provider,
            visual_mode=visual, repeat_fill=True, image={}, loop={}, final={},
            tracks=[] if provider == "upload" else h.new_tracks_from_plan(plan),
            status="planned",
        )
        manager.save_state(state)
        st.session_state.current_project = state
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 진행 패널 (백그라운드 작업)
# ─────────────────────────────────────────────────────────────────────────────
def _job_panel(st, state):
    pid = state["project_id"]

    @st.fragment(run_every=4)
    def _panel():
        job = h.get_job(pid)
        if job is None:
            return
        running = h.is_running(pid)
        if not running and job.get("_shown"):
            return
        with st.container(border=True):
            el = int((job.get("finished_at") or time.time()) - job["started_at"])
            head = "진행 중" if running else ("오류로 멈춤" if job["error"] else "끝")
            st.markdown(f"**⚙️ {job['label']} — {head}** · {el // 60}분 {el % 60:02d}초")
            st.progress(min(max(job.get("pct", 0.0), 0.0), 1.0), text=job.get("msg", ""))
            if job["error"]:
                st.error(job["error"])
            if running:
                if st.button("⏹ 중지", key=f"hz_stop_{pid}"):
                    h.request_stop(pid)
            else:
                job["_shown"] = True
                st.rerun()       # 결과를 화면 전체에 반영

    _panel()


# ─────────────────────────────────────────────────────────────────────────────
# 프로젝트 화면
# ─────────────────────────────────────────────────────────────────────────────
def _project(st, manager, api_keys):
    state = st.session_state.current_project
    pid = state["project_id"]
    plan = state.get("plan") or {}
    busy = h.is_running(pid)

    st.markdown(f"### {state.get('title', '')}")
    if plan.get("title_ko"):
        st.caption(plan["title_ko"])
    if plan.get("concept_ko"):
        st.write(plan["concept_ko"])
    _job_panel(st, state)

    # ── ② 그림 ──
    with st.container(border=True):
        st.markdown("**② 그림 (16:9 한 장)**")
        img = state.get("image") or {}
        local = h.ensure_local(api_keys, img, h.project_files(state, "image.jpg")) if img else ""
        if local:
            st.image(local, use_container_width=True)
        new_prompt = st.text_area("그림 프롬프트 (영문)", plan.get("image_prompt", ""), height=110, key=f"hz_ip_{pid}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🎨 그림 만들기" if not local else "🎨 다시 만들기", disabled=busy,
                         use_container_width=True, key=f"hz_img_{pid}"):
                if _keys_missing(api_keys, ["REPLICATE_API_TOKEN"]):
                    st.error("REPLICATE_API_TOKEN 이 없습니다.")
                else:
                    plan["image_prompt"] = new_prompt.strip()
                    with st.spinner("flux-dev 16:9 그림 만드는 중… (보통 20~60초)"):
                        try:
                            url = h.generate_image(api_keys["REPLICATE_API_TOKEN"], plan["image_prompt"])
                            h.save_image(api_keys, state, url, "flux-dev")
                            manager.save_state(state)
                            st.rerun()
                        except Exception as e:
                            st.error(f"그림 생성 실패: {e}")
        with c2:
            up = st.file_uploader("또는 내 그림 올리기 (JPG·PNG)", type=["jpg", "jpeg", "png"],
                                  key=f"hz_up_img_{pid}", disabled=busy)
            if up is not None and st.session_state.get(f"_hz_img_done_{pid}") != up.file_id:
                tmp = h.project_files(state, "upload_" + os.path.basename(up.name))
                with open(tmp, "wb") as f:
                    f.write(up.getvalue())
                h.save_image(api_keys, state, tmp, "upload")
                st.session_state[f"_hz_img_done_{pid}"] = up.file_id
                manager.save_state(state)
                st.rerun()
        if local and img.get("thumb_local") and os.path.exists(img["thumb_local"]):
            with open(img["thumb_local"], "rb") as f:
                st.download_button("⬇ 섬네일 바탕 그림 (1280×720)", f.read(), file_name="thumbnail_base.jpg",
                                   mime="image/jpeg", key=f"hz_thumb_{pid}")

    # ── ③ 움직임 ──
    with st.container(border=True):
        st.markdown("**③ 움직임 (반복 루프)**")
        mode = st.radio("화면", list(h.VISUAL_MODES), format_func=lambda k: h.VISUAL_MODES[k], horizontal=True,
                        index=list(h.VISUAL_MODES).index(state.get("visual_mode", "motion")), key=f"hz_vm_{pid}")
        if mode != state.get("visual_mode"):
            state["visual_mode"] = mode
            manager.save_state(state)
        if mode == "motion":
            mp = st.text_area("움직임 프롬프트 (영문) — 카메라 고정 문구는 자동으로 붙습니다",
                              plan.get("motion_prompt", ""), height=80, key=f"hz_mp_{pid}")
            if mp.strip() != plan.get("motion_prompt", ""):
                plan["motion_prompt"] = mp.strip()
                manager.save_state(state)
        loop = state.get("loop") or {}
        loop_local = h.ensure_local(api_keys, loop, h.project_files(state, "loop.mp4")) if loop else ""
        if loop_local:
            st.video(loop_local, loop=True, autoplay=True, muted=True)
            st.caption(f"{loop.get('seconds', 0)}초 루프 · 이 클립이 영상 끝까지 반복됩니다")
        has_img = bool(state.get("image"))
        if st.button("🔁 루프 만들기" if not loop_local else "🔁 루프 다시 만들기",
                     disabled=busy or not has_img, use_container_width=True, key=f"hz_loop_{pid}"):
            if mode == "motion" and _keys_missing(api_keys, ["REPLICATE_API_TOKEN"]):
                st.error("REPLICATE_API_TOKEN 이 없습니다.")
            else:
                h.start_loop_job(state, api_keys, manager.save_state)
                st.rerun()
        if not has_img:
            st.caption("② 그림을 먼저 준비해 주세요.")

    # ── ④ 음악 ──
    with st.container(border=True):
        st.markdown("**④ 음악**")
        prov = st.radio("만드는 방법", list(h.PROVIDERS), format_func=lambda k: h.PROVIDERS[k],
                        index=list(h.PROVIDERS).index(state.get("provider", "elevenlabs")), key=f"hz_pv_{pid}")
        if prov != state.get("provider"):
            state["provider"] = prov
            if prov != "upload" and not any(t.get("source") != "upload" for t in state.get("tracks", [])):
                state["tracks"] = state.get("tracks", []) + [
                    dict(t, no=len(state.get("tracks", [])) + i + 1) for i, t in enumerate(h.new_tracks_from_plan(plan))]
            manager.save_state(state)
            st.rerun()
        tracks = state.get("tracks", [])
        done = [t for t in tracks if t.get("status") == "done"]
        todo = [t["no"] for t in tracks if t.get("status") != "done" and t.get("source") != "upload"]
        total_unique = sum(t.get("seconds", 0) for t in done)
        st.caption(f"완성 {len(done)}/{len(tracks)}곡 · 곡 합계 {h.fmt_time(total_unique, True)} · "
                   f"목표 {h.LENGTH_OPTIONS.get(state.get('target_min', 60), '')} "
                   f"(모자라면 곡 목록 반복)")

        if prov in ("elevenlabs", "lyria") and todo:
            need = "ELEVENLABS_API_KEY" if prov == "elevenlabs" else "GOOGLE_API_KEY"
            label = f"🎵 남은 {len(todo)}곡 만들기"
            if prov == "elevenlabs":
                label += f" (≈ ${len(todo) * state.get('track_sec', 180) / 60 * h.EL_PRICE_PER_MIN:.2f})"
            if st.button(label, type="primary", disabled=busy, use_container_width=True, key=f"hz_mus_{pid}"):
                if _keys_missing(api_keys, [need]):
                    st.error(f"{need} 가 없습니다.")
                else:
                    h.start_music_job(state, api_keys, manager.save_state, todo)
                    st.rerun()
            if prov == "lyria":
                st.caption("Lyria 는 사이드바 「🔧 연결 테스트 → 🎵 Lyria 연결 테스트」가 성공한 뒤에 쓰세요. "
                           "연결 문제가 나면 첫 곡에서 바로 멈춥니다.")

        ups = st.file_uploader("Suno 등에서 만든 곡 올리기 (MP3·WAV·M4A, 여러 개 가능 · 파일 이름 = 곡 제목)",
                               type=["mp3", "wav", "m4a"], accept_multiple_files=True,
                               key=f"hz_up_mus_{pid}", disabled=busy)
        seen = st.session_state.setdefault(f"_hz_mus_seen_{pid}", [])
        added = 0
        for u in ups or []:
            if u.file_id in seen:
                continue
            try:
                h.add_uploaded_track(api_keys, state, u.name, u.getvalue())
                added += 1
            except Exception as e:
                st.error(str(e))
            seen.append(u.file_id)
        if added:
            manager.save_state(state)
            st.rerun()

        with st.expander(f"곡 목록 ({len(tracks)}곡)", expanded=bool(tracks) and len(done) < len(tracks)):
            for t in tracks:
                icon = {"done": "✅", "generating": "⚙️", "error": "❌"}.get(t.get("status"), "⏳")
                c1, c2 = st.columns([5, 1])
                with c1:
                    sec = f" · {h.fmt_time(t['seconds'])}" if t.get("seconds") else ""
                    st.markdown(f"{icon} **#{t['no']:02d} {t.get('title_ja', '')}** "
                                f"<small>{t.get('title_en', '')}{sec}</small>", unsafe_allow_html=True)
                    if t.get("error"):
                        st.caption(t["error"][:300])
                    if t.get("status") == "done" and h.usable(t.get("local", "")):
                        st.audio(t["local"])
                with c2:
                    if st.button("🗑", key=f"hz_del_{pid}_{t['no']}", disabled=busy, help="목록에서 빼기"):
                        state["tracks"] = [x for x in tracks if x["no"] != t["no"]]
                        state["final"] = {}
                        manager.save_state(state)
                        st.rerun()
                    if t.get("status") == "done" and t.get("source") != "upload":
                        if st.button("↻", key=f"hz_re_{pid}_{t['no']}", disabled=busy, help="이 곡 다시 만들기"):
                            t["status"] = "pending"
                            manager.save_state(state)
                            st.rerun()

    # ── ⑤ 합성 ──
    with st.container(border=True):
        st.markdown("**⑤ 최종 합성 (16:9 1920×1080)**")
        items = h.playlist(state)
        loop_ready = bool((state.get("loop") or {}).get("local") or (state.get("loop") or {}).get("r2_key"))
        if items:
            chs = h.chapters(items)
            est = chs[-1][0] + items[-1]["seconds"]
            st.caption(f"재생 순서 {len(items)}곡 · 예상 길이 {h.fmt_time(est, True)} · "
                       f"곡 사이 {int(h.XFADE_SEC)}초 크로스페이드 · 1시간 기준 합성 약 5~10분")
        if not h._r2_ok(api_keys):
            st.warning("R2 설정이 없어 완성 파일을 내려받을 링크를 만들 수 없습니다. "
                       "사이드바 「☁️ R2 연결 테스트」를 먼저 통과시켜 주세요.")
        if st.button("🎬 최종 영상 만들기", type="primary", disabled=busy or not items or not loop_ready,
                     use_container_width=True, key=f"hz_render_{pid}"):
            h.start_render_job(state, api_keys, manager.save_state)
            st.rerun()
        if not loop_ready:
            st.caption("③ 루프를 먼저 만들어 주세요.")
        elif not items:
            st.caption("④ 완성된 곡이 있어야 합니다.")

        fin = state.get("final") or {}
        if fin.get("seconds"):
            st.success(f"완성 — {h.fmt_time(fin['seconds'], True)} · {fin.get('bytes', 0) / 1e6:.0f}MB · "
                       f"{fin.get('made_at', '')}")
            link = h.final_link(api_keys, state)
            if link:
                st.link_button("⬇ 완성 영상 내려받기 (R2 · 7일간 유효)", link, use_container_width=True)
            elif h.usable(fin.get("local", "")) and fin.get("bytes", 0) < 200_000_000:
                with open(fin["local"], "rb") as f:
                    st.download_button("⬇ 완성 영상 내려받기", f.read(), file_name=os.path.basename(fin["local"]),
                                       mime="video/mp4", key=f"hz_dl_{pid}")

    # ── ⑥ 업로드 정보 ──
    fin = state.get("final") or {}
    if fin.get("seconds"):
        with st.container(border=True):
            st.markdown("**⑥ 업로드 정보 (일본어 · 곡 목록 챕터 포함)**")
            if st.button("📝 업로드 정보 만들기" if not state.get("upload_pack") else "📝 다시 만들기",
                         key=f"hz_pack_{pid}", use_container_width=True):
                with st.spinner("업로드 정보 작성 중…"):
                    h.make_upload_pack(api_keys.get("ANTHROPIC_API_KEY", ""), state)
                    manager.save_state(state)
            pack = state.get("upload_pack")
            if pack:
                st.markdown("제목")
                st.code(pack.get("title", ""), language=None)
                st.markdown("설명")
                st.code(pack.get("full_description", ""), language=None)
                st.markdown("태그")
                st.code(", ".join(pack.get("tags", [])), language=None)
                for k, v in h.UPLOAD_SETTINGS:
                    st.caption(f"{k} · {v}")


def render(st, manager, api_keys, show_banner):
    show_banner("hasira")
    cur = st.session_state.get("current_project")
    if cur is None:
        _new_project(st, manager, api_keys)
    else:
        _project(st, manager, api_keys)
