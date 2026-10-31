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
        '「낭만의 공간」 테마를 고르면 곡 프롬프트 · 그림 · 움직임을 준비하고, 1시간 16:9 영상으로 합성합니다. '
        '규칙은 「운영 규칙」 탭(매뉴얼 v5.0) 기준입니다.</p>',
        unsafe_allow_html=True,
    )
    board = h.load_board(api_keys)
    prompts_by_no = {t["no"]: t.get("prompts") or [] for t in h.load_series()}
    series = [dict(t, prompts=prompts_by_no.get(t["no"], []), status=t.get("stage", ""))
              for t in h.board_themes(board)]
    src = st.radio("테마 고르기", ["notion", "free"], horizontal=True, key="hz_src",
                   format_func=lambda k: {"notion": "제작 보드 테마 목록", "free": "새 테마 직접 입력"}[k])
    theme_obj, given = None, None
    if src == "notion" and series:
        pending = sorted([t for t in series if t.get("status") not in ("업로드 완료", "합성 완료")],
                         key=lambda t: (t.get("plan_month") or "9999", not t.get("prompts"), t["no"]))
        idx = series.index(pending[0]) if pending else 0
        theme_obj = st.selectbox("테마", series, index=idx, format_func=h.theme_label, key="hz_theme")
        if theme_obj.get("youtube_url"):
            st.caption(f"이미 올린 편 · {theme_obj['youtube_url']} · {theme_obj.get('memo', '')}")
        if theme_obj.get("prompts"):
            use_given = st.checkbox(f"저장된 프롬프트 {len(theme_obj['prompts'])}개(노션 LP 목록)를 그대로 사용 "
                                    f"(Top {sum(1 for p in theme_obj['prompts'] if p.get('top'))}곡 표시 유지)",
                                    value=True, key="hz_use_given")
            if use_given:
                given = theme_obj["prompts"]
        theme = f"{theme_obj['name_ko']} ({theme_obj['name_en']})"
    else:
        theme = st.text_input("새 테마 (한글 + 영문)", key="hz_kw",
                              placeholder="예: 마지막 전철 창가 (Last Train Window) / 눈 내리는 교토 거리 (Snowy Kyoto Street)")

    with st.form("hz_new", border=True):
        c1, c2 = st.columns(2)
        with c1:
            target = st.selectbox("영상 길이", list(h.LENGTH_OPTIONS), index=1,
                                  format_func=lambda k: h.LENGTH_OPTIONS[k], key="hz_target")
            provider = st.radio("음악 만드는 방법", list(h.PROVIDERS), index=list(h.PROVIDERS).index("elevenlabs"),
                                format_func=lambda k: h.PROVIDERS[k], key="hz_provider")
        with c2:
            track_min = st.select_slider("곡 하나 길이 (ElevenLabs·Lyria)", options=[2, 3, 4], value=3,
                                         format_func=lambda m: f"{m}분", key="hz_track_min")
            if given:
                n_tracks = len(given)
                st.caption(f"곡 수 · 노션 프롬프트 {n_tracks}곡")
            else:
                n_tracks = st.number_input("프롬프트(곡) 수", min_value=4, max_value=40, value=20, step=1,
                                           key="hz_n", help="매뉴얼: 1시간 = 20곡 내외, 곡당 2~4분")
            visual = st.radio("화면", list(h.VISUAL_MODES), index=list(h.VISUAL_MODES).index("kenburns"),
                              format_func=lambda k: h.VISUAL_MODES[k], key="hz_visual")
        if provider == "elevenlabs":
            st.caption(f"예상 음악 비용: {n_tracks}곡 × {track_min}분 × $0.15 ≈ "
                       f"${n_tracks * track_min * h.EL_PRICE_PER_MIN:.2f} (ElevenLabs 공식 API 요금 기준)")
        elif provider == "lyria":
            st.caption("Lyria 3.5 는 곡당 약 2분입니다. 요금은 Google 요금 문서에서 확인되지 않았습니다.")
        else:
            st.caption("Suno 는 공식 공개 API 가 없어 자동 연결하지 않습니다. ④ 단계에 곡마다 Suno 프롬프트가 나오고, "
                       "만든 MP3 를 그 자리에 올립니다. (매뉴얼: Suno Pro/Premier 상업 라이선스 필수)")
        go = st.form_submit_button("🎼 기획 만들기", type="primary", use_container_width=True)

    if go:
        if not (theme or "").strip():
            st.error("테마를 입력해 주세요.")
            return
        if _keys_missing(api_keys, ["ANTHROPIC_API_KEY"]):
            st.error("ANTHROPIC_API_KEY 가 없습니다.")
            return
        msg = ("노션 프롬프트는 그대로 두고 제목 · 그림 · 움직임 · 일본어 곡 제목을 정하는 중… (약 30초)" if given
               else "Claude 가 매뉴얼 정책으로 Suno 프롬프트 · 그림 · 움직임을 기획하는 중… (약 1분)")
        with st.spinner(msg):
            try:
                plan = h.make_plan(api_keys["ANTHROPIC_API_KEY"], theme, int(n_tracks), int(target), given=given)
            except Exception as e:
                st.error(f"기획 실패: {e}")
                return
        state = manager.create_new_project(chapter="HASIRA", topic=theme.strip(), channel="hasira")
        state.update(
            title=f"{(theme_obj or {}).get('no', '')}{'. ' if theme_obj else ''}{theme.strip()}",
            theme=theme.strip(), notion_theme_no=(theme_obj or {}).get("no", ""),
            plan=plan, keyword=theme.strip(), target_min=int(target), track_sec=int(track_min) * 60,
            provider=provider, visual_mode=visual, order_mode="in_order", repeat_fill=True,
            image={}, loop={}, final={}, voice={}, use_voice={"intro": True, "outro": True},
            tracks=h.new_tracks_from_plan(plan), status="planned",
        )
        if not theme_obj:                         # 직접 입력한 새 테마도 제작 보드에 올린다
            try:
                nt = h.add_theme(board, theme.strip(), "")
                h.save_board(api_keys, board)
                state["notion_theme_no"] = nt["no"]
            except Exception as e:
                print(f"[hasira] 보드에 새 테마 추가 실패: {e}", flush=True)
        manager.save_state(state)
        st.session_state.current_project = state
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 진행 패널 (백그라운드 작업)
# ─────────────────────────────────────────────────────────────────────────────
JOB_KIND_LABEL = {"loop": "③ 움직임 루프", "music": "④ 음악", "render": "⑤ 최종 합성"}


def _job_panel(st, state, where: str = "top", kinds: tuple = None):
    """백그라운드 작업 진행 표시. 4초마다 스스로 새로 고친다.
    where: 표시 위치(top · loop · music · render) — 같은 작업을 버튼 바로 옆에도 보여 준다.
    끝난 작업(완료·오류)은 다음 작업을 시작할 때까지 계속 보인다 (오류가 순식간에 사라지지 않게)."""
    pid = state["project_id"]

    @st.fragment(run_every=4)
    def _panel():
        job = h.get_job(pid)
        if job is None or (kinds and job.get("kind") not in kinds):
            return
        running = h.is_running(pid)
        el = int((job.get("finished_at") or time.time()) - job["started_at"])
        pct = min(max(job.get("pct", 0.0), 0.0), 1.0)
        with st.container(border=True):
            if running:
                st.markdown(f"**⏳ {job['label']} 진행 중** · {el // 60}분 {el % 60:02d}초 경과 · {int(pct * 100)}%")
                st.progress(pct, text=job.get("msg", "") or "작업 중…")
                st.caption("이 화면을 닫아도 서버에서 계속 진행됩니다. 4초마다 자동으로 새로 고칩니다.")
                if st.button("⏹ 중지", key=f"hz_stop_{pid}_{where}"):
                    h.request_stop(pid)
            elif job["error"]:
                st.markdown(f"**❌ {job['label']} 오류로 멈춤** · {el // 60}분 {el % 60:02d}초")
                st.error(job["error"])
            else:
                st.markdown(f"**✅ {job['label']} 끝** · {el // 60}분 {el % 60:02d}초")
                st.caption(job.get("msg", ""))
        if not running and not job.get("_refreshed") and where == "top":
            job["_refreshed"] = True
            st.rerun()       # 끝난 순간 한 번만 화면 전체를 새로 고쳐 결과(완성 링크 등)를 반영

    _panel()


def _busy_note(st, state, kind: str):
    """다른 작업 때문에 버튼이 잠겼을 때 이유를 버튼 바로 아래에 적는다."""
    job = h.get_job(state["project_id"])
    if job and h.is_running(state["project_id"]) and job.get("kind") != kind:
        st.caption(f"⏳ {job['label']} 작업이 진행 중이라 잠겨 있습니다. 끝나면 자동으로 풀립니다.")


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
    _job_panel(st, state, "top")

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
        if local:
            st.markdown("**섬네일 (1280×720 · 제목 글자 포함)**")
            _td = h.thumb_defaults(state)
            _th = state.get("thumbnail") or {}
            tc1, tc2 = st.columns([3, 2])
            with tc1:
                _big = st.text_input("큰 제목 (일본어)", _th.get("big") or _td["big"], key=f"hz_tb_{pid}")
            with tc2:
                _small = st.text_input("작은 줄 (영문)", _th.get("small") or _td["small"], key=f"hz_ts_{pid}")
            if st.button("🖼 섬네일 만들기" if not _th.get("local") else "🖼 섬네일 다시 만들기",
                         key=f"hz_tmk_{pid}", disabled=busy):
                try:
                    h.make_thumbnail(api_keys, state, _big, _small)
                    manager.save_state(state)
                    st.rerun()
                except Exception as e:
                    st.error(f"섬네일 만들기 실패: {e}")
            _tl = h.ensure_local(api_keys, _th, h.project_files(state, "thumbnail_1280x720.jpg")) if _th else ""
            if _tl:
                st.image(_tl, use_container_width=True)
                with open(_tl, "rb") as f:
                    st.download_button("⬇ 섬네일 내려받기 (1280×720 JPG)", f.read(), file_name="thumbnail.jpg",
                                       mime="image/jpeg", key=f"hz_tdl_{pid}")
            if img.get("thumb_local") and os.path.exists(img["thumb_local"]):
                with open(img["thumb_local"], "rb") as f:
                    st.download_button("⬇ 글자 없는 바탕 그림 (Canva 작업용)", f.read(), file_name="thumbnail_base.jpg",
                                       mime="image/jpeg", key=f"hz_thumb_{pid}")

    # ── ③ 움직임 ──
    with st.container(border=True):
        st.markdown("**③ 움직임 (반복 루프 · 매뉴얼: 완전 정지 금지)**")
        mode = st.radio("화면", list(h.VISUAL_MODES), format_func=lambda k: h.VISUAL_MODES[k], horizontal=True,
                        index=list(h.VISUAL_MODES).index(state.get("visual_mode")
                                                         if state.get("visual_mode") in h.VISUAL_MODES else "kenburns"),
                        key=f"hz_vm_{pid}")
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
        _busy_note(st, state, "loop")
        _job_panel(st, state, "loop", ("loop",))

    # ── ④ 음악 ──
    with st.container(border=True):
        st.markdown("**④ 음악**")
        prov = st.radio("만드는 방법", list(h.PROVIDERS), format_func=lambda k: h.PROVIDERS[k],
                        index=list(h.PROVIDERS).index(state.get("provider", "elevenlabs")), key=f"hz_pv_{pid}")
        if prov != state.get("provider"):
            state["provider"] = prov
            if not state.get("tracks") and plan.get("tracks"):      # 예전 프로젝트: 기획 목록 되살리기
                state["tracks"] = h.new_tracks_from_plan(plan)
            manager.save_state(state)
            st.rerun()
        tracks = state.get("tracks", [])
        done = [t for t in tracks if t.get("status") == "done"]
        todo = [t["no"] for t in tracks if t.get("status") != "done" and t.get("prompt")]
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

        if prov == "upload":
            st.markdown("Suno 작업 순서 (매뉴얼 Step 4) — **Instrumental** 을 켜고 ★Top 곡부터 프롬프트를 붙여 넣어 "
                        "A/B 2개씩 만든 뒤, QC 를 통과한 MP3 를 그 곡 자리에 올립니다.")
            st.download_button("⬇ Suno 작업용 곡 목록 (텍스트)", h.suno_sheet(state).encode("utf-8"),
                               file_name=f"suno_{pid}.txt", mime="text/plain", key=f"hz_suno_{pid}")
        _busy_note(st, state, "music")
        _job_panel(st, state, "music", ("music",))
        ups = st.file_uploader("곡 한꺼번에 올리기 (MP3·WAV·M4A, 여러 개 가능) — 비어 있는 자리부터 번호 순서로 채웁니다. "
                               "자리가 다 차면 목록 끝에 추가되고 파일 이름이 곡 제목이 됩니다.",
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
            for t in sorted(tracks, key=lambda x: x["no"]):
                icon = {"done": "✅", "generating": "⚙️", "error": "❌"}.get(t.get("status"), "⏳")
                c1, c2 = st.columns([5, 1])
                with c1:
                    sec = f" · {h.fmt_time(t['seconds'])}" if t.get("seconds") else ""
                    star = "★ " if t.get("top") else ""
                    code = f"{t['code']} · " if t.get("code") else ""
                    ko = f" · {t['title_ko']}" if t.get("title_ko") else ""
                    st.markdown(f"{icon} **#{t['no']:02d} {star}{t.get('title_ja', '')}** "
                                f"<small>{code}{t.get('title_en', '')}{ko}{sec}</small>", unsafe_allow_html=True)
                    if t.get("error"):
                        st.caption(t["error"][:300])
                    if t.get("status") == "done" and h.usable(t.get("local", "")):
                        if t.get("source") == "upload" and t.get("file_name"):
                            st.caption(f"올린 파일 · {t['file_name']}")
                        st.audio(t["local"])
                    elif prov == "upload" and t.get("prompt"):
                        st.code(h.suno_style(state, t), language=None)
                        one = st.file_uploader(f"#{t['no']:02d} 자리에 올리기", type=["mp3", "wav", "m4a"],
                                               key=f"hz_slot_{pid}_{t['no']}", disabled=busy,
                                               label_visibility="collapsed")
                        if one is not None and one.file_id not in seen:
                            seen.append(one.file_id)
                            try:
                                h.add_uploaded_track(api_keys, state, one.name, one.getvalue(), no=t["no"])
                                manager.save_state(state)
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
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

    # ── ④-2 인트로·아웃트로 목소리 ──
    with st.container(border=True):
        st.markdown("**④-2 인트로 · 아웃트로 목소리 (매뉴얼 Part 0 · 내 목소리 5~10초)**")
        st.caption("아웃트로는 한 번 올리면 R2 공용 보관함에 저장돼 다음 편에도 자동으로 들어갑니다. 인트로는 테마가 바뀌므로 편마다 올립니다. "
                   "읽을 대사는 바로 아래에 있습니다.")
        _th = h.load_board(api_keys).get("themes", {}).get(state.get("notion_theme_no", ""), {})
        _op = h.opening_lines(_th)
        dc = st.columns(2)
        with dc[0]:
            if _op:
                st.markdown("인트로 대사")
                st.code(_op["ja"], language=None)
                st.caption(f"읽기 · {_op['read']}  \n한글 발음 · {_op['hangul']}  \n뜻 · {_op['ko']}")
            else:
                st.caption("이 테마는 인트로 대사가 아직 없습니다. 제작 보드 「대사」 탭 틀에 장소 이름만 넣어 읽으면 됩니다.")
        with dc[1]:
            st.markdown("아웃트로 대사 (공통)")
            st.code(h.CLOSING["ja"], language=None)
            st.caption(f"한글 발음 · {h.CLOSING['hangul']}  \n뜻 · {h.CLOSING['ko']}")
        uv = state.setdefault("use_voice", {"intro": True, "outro": True})
        vc = st.columns(2)
        for col, kind in zip(vc, h.VOICE_KINDS):
            with col:
                v = (state.get("voice") or {}).get(kind) or {}
                on = st.checkbox(f"{h.VOICE_KINDS[kind]} 넣기", value=uv.get(kind, True), key=f"hz_uv_{kind}_{pid}")
                if on != uv.get(kind, True):
                    uv[kind] = on
                    state["final"] = {}
                    manager.save_state(state)
                if v.get("local") and h.usable(v["local"]):
                    st.caption(f"{v.get('file_name', '')} · {v.get('seconds', 0)}초")
                    st.audio(v["local"])
                vf = st.file_uploader(f"{h.VOICE_KINDS[kind]} 파일 (MP3·WAV·M4A)", type=["mp3", "wav", "m4a"],
                                      key=f"hz_voice_{kind}_{pid}", disabled=busy)
                vseen = st.session_state.setdefault(f"_hz_voice_seen_{pid}", [])
                if vf is not None and vf.file_id not in vseen:
                    vseen.append(vf.file_id)
                    try:
                        h.save_voice(api_keys, state, kind, vf.name, vf.getvalue())
                        manager.save_state(state)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    # ── ⑤ 합성 ──
    with st.container(border=True):
        st.markdown("**⑤ 최종 합성 (1920×1080 · 30fps · AAC 320kbps · -14 LUFS · 곡 사이 2초 크로스페이드)**")
        om = st.radio("곡 배치", list(h.ORDER_MODES), format_func=lambda k: h.ORDER_MODES[k], horizontal=True,
                      index=list(h.ORDER_MODES).index(state.get("order_mode", "in_order")), key=f"hz_om_{pid}")
        if om != state.get("order_mode", "in_order"):
            state["order_mode"] = om
            state["final"] = {}
            manager.save_state(state)
        items = h.playlist(state)
        loop_ready = bool((state.get("loop") or {}).get("local") or (state.get("loop") or {}).get("r2_key"))
        if items:
            chs = h.chapters(items)
            est = chs[-1][0] + items[-1]["seconds"]
            st.caption(f"재생 순서 {len(items)}곡 · 예상 길이 {h.fmt_time(est, True)} · "
                       f"인트로·아웃트로 제외 · 1시간 기준 합성 약 5~10분")
        if not h._r2_ok(api_keys):
            st.warning("R2 설정이 없어 완성 파일을 내려받을 링크를 만들 수 없습니다. "
                       "사이드바 「☁️ R2 연결 테스트」를 먼저 통과시켜 주세요.")
        _rjob = h.get_job(pid)
        _rendering = busy and _rjob and _rjob.get("kind") == "render"
        if st.button("⏳ 최종 영상 만드는 중… (아래 진행 표시)" if _rendering else "🎬 최종 영상 만들기",
                     type="primary", disabled=busy or not items or not loop_ready,
                     use_container_width=True, key=f"hz_render_{pid}"):
            h.start_render_job(state, api_keys, manager.save_state)
            st.rerun()
        _busy_note(st, state, "render")
        _job_panel(st, state, "render", ("render",))
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
                if pack.get("banned_in_title"):
                    st.warning("제목에 금지어가 있습니다: " + ", ".join(pack["banned_in_title"]))
                if pack.get("description_chars", 0) and pack["description_chars"] < 250:
                    st.warning(f"설명 첫 부분이 {pack['description_chars']}자입니다 (매뉴얼: 250자 이상).")
                for k, v in h.UPLOAD_SETTINGS:
                    st.caption(f"{k} · {v}")


# ─────────────────────────────────────────────────────────────────────────────
# 제작 보드 · 대사 · 운영 규칙 (노션 대신)
# ─────────────────────────────────────────────────────────────────────────────
RULES_MD = """
**채널 정의** · 힐링과 성장을 위한 감정 기록 채널. 낮과 밤을 가리지 않고 낭만과 로망이 머무는 순간을 음악으로 기록한다.
"카페 음악"이 아닌 "영화적 낭만을 일상에 붙이는 채널". 중심 시리즈 「낭만의 공간」.

**대상 · 색감** · 일본 40~60대 + 글로벌 Cinematic Classical 리스너 · 벚꽃 톤(웜 로즈/앰버)

**브랜드 서명** · 行福しなさい、癒しなさい。今日もしばらく寄りかかってください。

**금지어 (제목·태그·설명)** · cafe music, jazz, lo-fi, BGM, study music, AI music, Suno

**곡 프롬프트 정책** · 장르 선언(Cinematic romantic classical instrumental) → Atmosphere(감각 묘사) →
Instruments(피아노 + 첼로·바이올린·비올라, 보조 하프·피치카토·패드) → Tempo(BPM 54~68) → Guardrails("No …" 3개 이상).
금지: jazz, 드럼·퍼커션, 전자음, 밝은 고주파, 급격한 다이나믹, 촬영 용어, 보컬

**QC 기준** · 30초: 분위기 안정 / 2분: 감정 과잉 없음 / 전체: 영화 엔딩 크레딧에 어울림. 폐기 사유 1줄(상업BGM·웅장·감정과잉 등)

**1시간 구성** · 20곡 내외(곡당 2~4분) · 배치 번호순 또는 ABACAD · 곡 사이 크로스페이드 · -14 LUFS ·
1920×1080 30fps H.264, AAC 320kbps · 화면은 Ken Burns 1~3%(완전 정지 금지)

**사람의 몫 (수익화 대비)** · 내 목소리 인트로·아웃트로 5~10초 / 업로드 시 AI 도구 사용 공개 체크 /
설명란에 선곡 의도·감정 설계 1~2줄

**업로드** · 제목: 검색 키워드 + 감정 문장 + HASIRA_yo! (예: Cinematic Piano 1 Hour | 温泉旅館の夜 — 静かな時間をあなたに | HASIRA_yo!)
· 설명 250자+ · 챕터 · 브랜드 서명 · #태그 3~5 · 태그 15~20 · 썸네일 벚꽃 톤

**운영 리듬 (2026-10 결정)** · Long-form 월 2편(첫째·셋째 금요일 20:00 JST) · 나머지 주는 Shorts ·
두 달에 한 번 4편을 묶은 Vol 편 · ElevenLabs Creator 월 147분 안에서 운영

**키워드 3층** · 검색: cinematic piano 1 hour, シネマティック ピアノ 1時間, relaxing classical music /
니치: cinematic end credit piano music, 映画のエンドクレジット風ピアノ, romantic classical instrumental for reading /
브랜드: HASIRA_yo + 테마
"""


def _board_tab(st, manager, api_keys):
    import pandas as pd
    board = h.load_board(api_keys)
    themes = h.board_themes(board)
    # 이 서버에 남아 있는 프로젝트로 진행 상황 갱신
    for p in manager.list_projects():
        if p.get("channel") == "hasira":
            try:
                h.sync_board(api_keys, manager.load_state(p["dir"]))
            except Exception:
                pass
    board = h.load_board(api_keys)
    themes = h.board_themes(board)
    counts = {s: sum(1 for t in themes if t.get("stage") == s) for s in h.STAGES}
    st.caption(" · ".join(f"{k} {v}" for k, v in counts.items()) +
               (f" · 마지막 저장 {board.get('updated')}" if board.get("updated") else ""))
    df = pd.DataFrame([{
        "번호": t["no"], "테마": t["name_ko"], "영문": t["name_en"], "단계": t.get("stage", "예정"),
        "진행": t.get("detail", ""), "예정월": t.get("plan_month", ""), "YouTube": t.get("youtube_url", ""),
        "Shorts": t.get("shorts_url", ""), "업로드일": t.get("upload_date", ""),
        "1주 조회수": t.get("views_1w"), "메모": t.get("memo", ""),
    } for t in themes])
    edited = st.data_editor(
        df, hide_index=True, use_container_width=True, key="hz_board_editor",
        disabled=["번호", "진행"],
        column_config={
            "단계": st.column_config.SelectboxColumn(options=h.STAGES, width="small"),
            "YouTube": st.column_config.LinkColumn(), "Shorts": st.column_config.LinkColumn(),
            "1주 조회수": st.column_config.NumberColumn(format="%d"),
            "예정월": st.column_config.TextColumn(help="예: 2026-11"),
        },
    )
    if st.button("💾 보드 저장", type="primary", key="hz_board_save"):
        for _, row in edited.iterrows():
            t = board["themes"].get(row["번호"])
            if t is None:
                continue
            t.update(name_ko=row["테마"], name_en=row["영문"], stage=row["단계"], plan_month=row["예정월"] or "",
                     youtube_url=row["YouTube"] or "", shorts_url=row["Shorts"] or "",
                     upload_date=row["업로드일"] or "", memo=row["메모"] or "",
                     views_1w=None if pd.isna(row["1주 조회수"]) else int(row["1주 조회수"]))
            if t["youtube_url"] and t["stage"] != "업로드 완료":
                t["stage"] = "업로드 완료"
        where = h.save_board(api_keys, board)
        st.success("저장했습니다 (R2)." if where == "r2" else "저장했습니다. R2 설정이 없어 이 서버에만 남습니다.")
        st.rerun()
    with st.expander("✚ 새 테마 추가"):
        with st.form("hz_add_theme", border=False):
            c1, c2 = st.columns(2)
            nk = c1.text_input("테마 (한글)", placeholder="마지막 전철 창가")
            ne = c2.text_input("영문", placeholder="Romance Last Train Window")
            pj = c1.text_input("인트로에 넣을 일본어 장소 (선택)", placeholder="終電の窓辺")
            pr = c2.text_input("그 읽기 (선택)", placeholder="しゅうでんの まどべ")
            ph = c1.text_input("한글 발음 (선택)", placeholder="슈-덴노 마도베")
            if st.form_submit_button("추가"):
                if nk.strip() and ne.strip():
                    h.add_theme(board, nk, ne, pj, pr, ph)
                    h.save_board(api_keys, board)
                    st.rerun()
                else:
                    st.error("한글·영문 테마 이름을 넣어 주세요.")


def _lines_tab(st, api_keys):
    st.markdown("인트로는 편마다 테마에 맞는 것을, 아웃트로는 공통 하나를 한 번만 녹음해 ④-2 칸에 올립니다. "
                "조용한 방에서 핸드폰과 입 사이 한 뼘, 말 앞뒤로 1초씩 비우고 평소보다 한 박자 느리게 읽습니다. "
                "아이폰 음성 메모(.m4a)를 그대로 올려도 됩니다.")
    st.markdown("**아웃트로 (공통 · 약 10초)**")
    st.code(h.CLOSING["ja"], language=None)
    st.caption(f"읽기 · {h.CLOSING['read']}  \n한글 발음 · {h.CLOSING['hangul']}  \n뜻 · {h.CLOSING['ko']}  \n"
               "10초를 넘기면 마지막 구독 문장을 빼고 브랜드 서명까지만 녹음합니다.")
    st.markdown("**인트로 (테마별 · 약 7초)**")
    for t in h.board_themes(h.load_board(api_keys)):
        op = h.opening_lines(t)
        with st.container(border=True):
            st.markdown(f"**{t['no']}. {t['name_ko']}** · {t.get('stage', '')}")
            if op:
                st.code(op["ja"], language=None)
                st.caption(f"한글 발음 · {op['hangul']}  \n뜻 · {op['ko']}")
            else:
                st.caption("일본어 장소 이름이 없습니다 — 틀: " + h.OPENING_TMPL.format(place="＿＿＿"))


def render(st, manager, api_keys, show_banner):
    show_banner("hasira")
    cur = st.session_state.get("current_project")
    if cur is None:
        t1, t2, t3, t4 = st.tabs(["📋 제작 보드", "🎼 새 편 만들기", "🎙 대사", "📖 운영 규칙"])
        with t1:
            _board_tab(st, manager, api_keys)
        with t2:
            _new_project(st, manager, api_keys)
        with t3:
            _lines_tab(st, api_keys)
        with t4:
            st.markdown(RULES_MD)
    else:
        try:
            h.sync_board(api_keys, cur)
        except Exception as e:
            print(f"[hasira] 보드 갱신 실패: {e}", flush=True)
        _project(st, manager, api_keys)
