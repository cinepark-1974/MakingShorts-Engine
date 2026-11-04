# src/rodoku_comp.py
# SceneStory 朗読ドラマ 모음편 (약 1시간) — 이미 만든 본편 3~4편을 이어 붙인다.
#
# 편마다 본편 파일을 찾는 순서 (앞에서 찾으면 멈춤)
#   ① 서버에 남은 본편 파일
#   ② R2 에 보관된 본편 파일
#   ③ R2 에 남은 재료(그림·움직임·낭독·음악)로 본편을 다시 합성
#   ④ 작가가 직접 올린 본편 파일 (내려받아 둔 mp4)
# 셋 다 없으면 그 편은 건너뛰고 이유를 남긴다.

import copy
import json
import os
import shutil
import subprocess
import time

from src import hasira as hz
from src import rodoku as R

CARD_SEC = 5.0
COMP_PACK_SYSTEM = """あなたはYouTubeチャンネル「SceneStory」（60〜70代向けオリジナル朗読ドラマ）のアップロード担当です。
複数の短編をまとめた約1時間の動画のタイトル等を作ります。JSONだけを出力:
{"title": "【朗読ドラマ】で始め、話数と聴く場面が分かるタイトル（60字以内。例：【朗読ドラマ】眠る前に聴く、人生の短編3話｜1時間）",
 "cover": "サムネイルに大きく入れる言葉（14字以内。例：眠る前の、三つの物語）",
 "description": "3〜4行。収録作それぞれの一行紹介（結末は書かない）と、寝る前・家事の合間にどうぞの一言。",
 "tags": ["検索語 12〜15個"],
 "pinned_comment": "固定コメント。2行。どの話がいちばん心に残ったかを聞く問いかけで終える"}
誇張・扇情的な表現は使わない。"""


# ─────────────────────────────────────────────────────────────────────────────
# 편 목록
# ─────────────────────────────────────────────────────────────────────────────
def _probe(path: str) -> dict:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                              "-of", "json", path], capture_output=True, text=True, timeout=60).stdout
        st = json.loads(out).get("streams", [])
        v = next((s for s in st if s.get("codec_type") == "video"), {})
        a = next((s for s in st if s.get("codec_type") == "audio"), {})
        return {"v": (v.get("codec_name"), v.get("width"), v.get("height"), v.get("r_frame_rate")),
                "a": (a.get("codec_name"), str(a.get("sample_rate")), a.get("channels"))}
    except Exception:
        return {}


STD = {"v": ("h264", hz.W, hz.H, f"{hz.FPS}/1"), "a": ("aac", "44100", 2)}


def episodes(manager, keys: dict) -> list:
    """완성된 朗読ドラマ 편 목록 (최신순). 서버 목록 + R2 기록을 합친다."""
    seen, out = set(), []
    for p in manager.list_projects():
        if p.get("channel") != "scenestory":
            continue
        try:
            st = manager.load_state(p["dir"])
        except Exception:
            continue
        if st.get("mode") != "rodoku" or not (st.get("final") or {}).get("seconds"):
            continue
        seen.add(st["project_id"])
        out.append(st)
    for pid in sorted(R.cloud_index(keys), reverse=True):
        if pid in seen:
            continue
        try:
            st = R.cloud_state(keys, pid)
        except Exception:
            continue
        if st.get("mode") == "rodoku" and (st.get("final") or {}).get("seconds"):
            out.append(st)
    out.sort(key=lambda s: s.get("project_id", ""), reverse=True)
    return out


def source_of(keys: dict, ep: dict, uploads: dict) -> str:
    """이 편의 본편을 어디서 가져올 수 있는지: local / r2 / rebuild / upload / none"""
    fin = ep.get("final") or {}
    if hz.usable(fin.get("local", "")):
        return "local"
    if fin.get("r2_key") and hz._r2_ok(keys):
        return "r2"
    chs = ep.get("chapters") or []
    if chs and hz._r2_ok(keys) and all((c.get("image") or {}).get("r2_key") and (c.get("audio") or {}).get("r2_key")
                                       for c in chs):
        return "rebuild"
    if hz.usable(uploads.get(ep.get("project_id", ""), "")):
        return "upload"
    return "none"


SOURCE_LABEL = {"local": "서버에 본편 있음", "r2": "R2 에 본편 있음", "rebuild": "본편 없음 → R2 재료로 다시 합성",
                "upload": "올린 파일 사용", "none": "본편·재료 없음 → 내려받아 둔 mp4 를 올려 주세요"}


# ─────────────────────────────────────────────────────────────────────────────
# 제작
# ─────────────────────────────────────────────────────────────────────────────
def start(state: dict, keys: dict, save_fn) -> bool:
    def save_both(s):
        save_fn(s)
        R.save_cloud(keys, s)
    return hz._start(state["project_id"], "rodoku_comp", "모음편 만들기", _worker, (state, keys, save_both))


def _cf(state, *parts):
    d = os.path.join(state["project_dir"], "comp", *parts[:-1])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, parts[-1])


def _rebuild(job, ep: dict, keys: dict, work_dir: str) -> str:
    """R2 의 재료로 본편을 다시 합성 (작업 폴더는 모음편 프로젝트 안)."""
    st = copy.deepcopy(ep)
    st["project_dir"] = work_dir
    for c in st["chapters"]:
        for k, name in (("image", f"ch{c['no']:02d}.jpg"), ("audio", f"ch{c['no']:02d}.mp3")):
            if c.get(k):
                c[k]["local"] = ""          # 원래 프로젝트 경로가 아니라 이 작업 폴더로 받는다
                if not hz.ensure_local(keys, c[k], R.pf(st, name)):
                    raise RuntimeError(f"제{c['no']}장 재료({k})를 R2 에서 받지 못했습니다")
        if (c.get("motion") or {}).get("r2_key"):
            c["motion"]["local"] = ""
            hz.ensure_local(keys, c["motion"], R.pf(st, f"ch{c['no']:02d}_motion.mp4"))
    for kind in ("a", "b"):
        it = (st.get("bgm") or {}).get(kind) or {}
        if it:
            it["local"] = ""
            hz.ensure_local(keys, it, R.pf(st, "music", f"bgm_{kind}.mp3"))
    if st.get("outro"):
        st["outro"]["local"] = ""
        hz.ensure_local(keys, st["outro"], R.pf(st, "outro.mp3"))
    st["final"] = {}
    R._render(job, st, {k: v for k, v in keys.items() if not k.startswith("R2_")}, lambda s: None)   # R2 에 다시 올리지 않음
    return st["final"]["local"]


def _fetch(job, state, keys, ep: dict) -> str:
    pid = ep["project_id"]
    src = source_of(keys, ep, state.get("uploads") or {})
    fin = ep.get("final") or {}
    if src == "local":
        return fin["local"]
    if src == "r2":
        dest = _cf(state, "src", f"{pid}.mp4")
        if hz.usable(dest):
            return dest
        from src import r2_store
        r2_store.download_file(keys, fin["r2_key"], dest)
        return dest
    if src == "rebuild":
        return _rebuild(job, ep, keys, os.path.dirname(_cf(state, "rebuild", pid, "x")))
    if src == "upload":
        return state["uploads"][pid]
    raise RuntimeError("본편 파일과 재료가 모두 없습니다")


def _standardize(src: str, out: str) -> str:
    """규격이 다른 파일(직접 올린 파일 등)만 본편 규격으로 다시 인코딩."""
    if _probe(src) == STD:
        return src
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", f"{hz.FILL},fps={hz.FPS},format=yuv420p",
                    *hz.X264, "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                    "-movflags", "+faststart", out], check=True, timeout=7200)
    return out


def _card_video(bg_img: str, big: str, small: str, out: str, sec: float = CARD_SEC) -> str:
    """그림 한 장 + 카드 글자 + 무음 → 본편과 같은 규격의 짧은 클립."""
    png = out.replace(".mp4", ".png")
    R._card_png(png, big, small)
    fc = (f"[0:v]{hz.FILL},format=yuv420p[b];[1:v]format=rgba,fade=t=in:st=0:d=0.6:alpha=1,"
          f"fade=t=out:st={sec - 0.6:.2f}:d=0.6:alpha=1[o];[b][o]overlay=0:0,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(hz.FPS), "-t", f"{sec}", "-i", bg_img,
                    "-loop", "1", "-framerate", str(hz.FPS), "-t", f"{sec}", "-i", png,
                    "-f", "lavfi", "-t", f"{sec}", "-i", "anullsrc=r=44100:cl=stereo",
                    "-filter_complex", fc, "-map", "[v]", "-map", "2:a", *hz.X264, "-crf", "20",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{sec}", "-movflags", "+faststart", out],
                   check=True, timeout=600)
    return out


def _ep_image(keys, state, ep) -> str:
    c = next((x for x in ep.get("chapters") or [] if x.get("with_young")), (ep.get("chapters") or [{}])[0])
    img = c.get("image") or {}
    return hz.ensure_local(keys, img, _cf(state, "img", f"{ep['project_id']}.jpg")) if img else ""


def _worker(job, state, keys, save_fn):
    eps = state["comp"]["episodes"]          # [{pid, title, state}]
    kanji = "一二三四五六七八九十"
    job["total"] = len(eps)
    parts, marks, skipped, t = [], [], [], 0.0
    titles = [e["title"] for e in eps]
    first_img = ""
    for i, e in enumerate(eps):
        ep = e["state"]
        job["done"] = i
        job["msg"] = f"제{i + 1}화 『{e['title']}』 본편 가져오는 중 ({SOURCE_LABEL[source_of(keys, ep, state.get('uploads') or {})]})"
        try:
            mp4 = _fetch(job, state, keys, ep)
            mp4 = _standardize(mp4, _cf(state, "std", f"{ep['project_id']}.mp4"))
        except Exception as ex:
            skipped.append(f"{e['title']}: {type(ex).__name__}: {ex}"[:200])
            print(f"[rodoku_comp] {e['title']} 건너뜀: {ex}", flush=True)
            continue
        img = _ep_image(keys, state, ep) or first_img
        first_img = first_img or img
        no = len(marks)
        label = f"第{kanji[no] if no < 10 else no + 1}話"
        if img:
            parts.append(_card_video(img, e["title"], label, _cf(state, "work", f"card{no + 1:02d}.mp4")))
        marks.append((t, f"{label}『{e['title']}』"))
        t += (CARD_SEC if img else 0) + hz.duration(mp4)
        parts.append(mp4)
        if job.get("stop"):
            raise RuntimeError("중지했습니다.")
    if len(marks) < 2:
        raise RuntimeError("이어 붙일 본편이 2편 이상 필요합니다. " + " / ".join(skipped))
    job["msg"] = f"{len(marks)}편 이어 붙이는 중"
    lst = _cf(state, "work", "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    out = _cf(state, f"SceneStory_comp_{state['project_id']}.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", "-movflags", "+faststart", out], check=True, timeout=3600)
    info = {"local": out, "seconds": round(hz.duration(out), 2), "bytes": os.path.getsize(out),
            "chapters": [[round(a, 2), b] for a, b in marks], "skipped": skipped,
            "made_at": time.strftime("%Y-%m-%d %H:%M")}
    job["msg"] = f"R2 에 올리는 중 ({info['bytes'] / 1e6:.0f}MB)"
    info["r2_key"] = R.keep(keys, state, out, os.path.basename(out), "video/mp4")
    state["final"] = info
    hz._save(save_fn, state)

    # 업로드 정보 · 섬네일
    job["msg"] = "섬네일·업로드 정보 만드는 중"
    ok_titles = [m[1] for m in marks]
    pack = {"title": f"【朗読ドラマ】眠る前に聴く、人生の短編{len(marks)}話｜{hz.fmt_time(info['seconds'], True)}",
            "cover": f"眠る前の、{len(marks)}つの物語", "description": "", "tags": ["朗読", "朗読ドラマ", "睡眠用", "作業用"],
            "pinned_comment": "どのお話が、いちばん心に残りましたか。"}
    try:
        user = "収録作:\n" + "\n".join(f"- {x}" for x in ok_titles) + f"\n長さ: {hz.fmt_time(info['seconds'], True)}"
        pack.update({k: v for k, v in R._json_call(keys.get("ANTHROPIC_API_KEY", ""), COMP_PACK_SYSTEM, user, 1500).items() if v})
    except Exception as ex:
        print(f"[rodoku_comp] 업로드 정보 생성 실패 → 기본값: {ex}", flush=True)
    body = (pack.get("description") or "").strip()
    body += "\n\n― 目次 ―\n" + hz.chapter_text([(a, b) for a, b in marks], info["seconds"])
    body += "\n\n脚本家が書き下ろしたオリジナル短編です。登場人物・団体は架空のものです。\n\n#朗読 #朗読ドラマ #睡眠用"
    pack["full_description"] = body
    state["upload_pack"] = pack
    if first_img:
        proxy = {"project_id": state["project_id"], "project_dir": state["project_dir"],
                 "image": {"local": first_img}, "thumbnail": {}}
        try:
            hz.make_thumbnail(keys, proxy, pack.get("cover") or pack["title"], "SCENESTORY · 朗読ドラマ", brand="SceneStory")
            th = proxy["thumbnail"]
            state["thumbnail"] = {"local": th["local"], "r2_key": R.keep(keys, state, th["local"], "thumbnail.jpg", "image/jpeg")}
        except Exception as ex:
            state["thumbnail"] = {"error": str(ex)[:200]}
    state["stage"] = "done"
    state["title"] = pack["title"]
    hz._save(save_fn, state)
    job["done"] = len(eps)
    job["msg"], job["pct"] = f"완성 — {hz.fmt_time(info['seconds'], True)} · {len(marks)}편", 1.0
