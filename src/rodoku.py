# src/rodoku.py
# SceneStory 朗読ドラマ — 완전 자동 제작 라인 (일본 시니어 · 16:9 · 15~20분)
#
# 버튼 한 번으로:
#   ① 트렌드  : 일본 YouTube 자동완성(hl=ja, gl=JP)으로 시니어 연애 검색어를 모은다
#   ② 소재·설계: Claude 가 검색어 중 하나를 골라 인물·장소·사물·반전·장 구성을 정한다
#   ③ 집필    : 장마다 일본어 본문 (Novel-Engine 집필 규칙 M1·M2·M11·M12·M13·M18 적용)
#   ④ 그림    : 장마다 수채 스케치 16:9 한 장 (얼굴 없음)
#   ⑤ 목소리  : 장마다 ElevenLabs 일본어 낭독 (eleven_v4 → 실패 시 multilingual_v2)
#   ⑥ 합성    : 오프닝 카드 + 장 제목 카드 + Ken Burns 반복 화면 + 낭독 + 잔잔한 피아노
#   ⑦ 예고편  : 가장 아픈 대목 30~50초 → 9:16 쇼츠 (큰 자막)
#   ⑧ 섬네일·업로드 정보 (일본어, 장 타임스탬프)
# 작가는 완성본을 확인하고 YouTube 에 올리기만 한다.
#
# 오래 걸리므로 백그라운드 작업으로 돈다. 단계마다 저장하므로 중간에 끊겨도 '이어서 만들기'로 남은 단계만 한다.
# 이 모듈 안에서는 st.* 를 호출하지 않는다.

import json
import os
import re
import shutil
import subprocess
import time

from src import hasira as hz

JA_VOICE_ID = "wcs09USXSN5Bl7FXohVZ"     # SceneStory 일본어 낭독 (Mr. MOON 선택)
JA_CPS = 4.13                            # 이 목소리 실측 초당 글자 수 (voice_test)
OPEN_CARD_SEC = 6.0
TITLE_CARD_SEC = 4.0
CHAPTER_PAD_SEC = 1.2
BGM_VOLUME = 0.10

LENGTHS = {15: {"label": "약 15분 (5장)", "chapters": 5}, 20: {"label": "약 20분 (6장)", "chapters": 6}}
DEFAULT_MIN = 15

# 일본 시니어 연애·인생 검색 씨앗 — 자동완성으로 실제 검색어를 모은다
SEEDS_JA = [
    "シニア恋愛", "熟年 恋愛", "初恋 再会", "同窓会 再会", "定年後 恋", "黄昏 恋愛", "熟年離婚",
    "夫婦 秘密", "朗読 恋愛", "昭和 恋", "未亡人 恋", "人生の後半 恋", "老後 恋", "朗読ドラマ",
    "初恋の人", "妻に言えない", "夫に言えない", "70代 恋",
]
_BLOCK_JA = ["歌", "曲", "カラオケ", "mv", "ドラマ 無料", "アニメ", "漫画", "ゲーム", "占い", "アプリ",
             "マッチング", "婚活", "出会い", "風俗", "エロ", "av", "ニュース", "芸能", "炎上"]

# 이야기의 '종류' — 편마다 최근 6편에 안 쓴 종류 하나를 엔진이 먼저 고르고, 그 종류의 검색어로 트렌드를 조회한다.
# (예전에는 씨앗 검색어가 '첫사랑·재회·동창회' 쪽으로 쏠려 '40년 만의 편지' 이야기가 반복됐다)
STORY_KINDS = [
    ("夫婦の秘密", "長年連れ添った夫婦。どちらかが何十年も言わずにきた小さな秘密が、ある日の出来事で表に出る",
     ["夫婦 秘密", "妻に言えない", "夫に言えない"]),
    ("定年後の再出発", "定年や引退のあと、新しい仕事・習い事・役目を始めた人が、そこで思いがけない人と関わる",
     ["定年後 生きがい", "定年後 夫婦", "シニア 習い事"]),
    ("遺品整理", "亡くなった家族の部屋を片付けていて、知らなかった一面を示す物が出てくる",
     ["遺品整理 思い出", "形見 泣ける"]),
    ("嫁と姑", "嫁と姑、義理の親子。長い確執か遠慮が、ひとつの出来事で崩れる",
     ["嫁姑 和解", "義母 本音"]),
    ("孫との一日", "祖父母と孫が二人きりで過ごす一日。孫の一言が祖父母の人生の何かを動かす",
     ["祖母と孫 泣ける", "孫 一日"]),
    ("隣人", "団地・アパート・町内の隣人。毎日顔を合わせるのに知らなかった事情を、ある夜に知る",
     ["団地 隣人", "ご近所付き合い 高齢"]),
    ("店じまい", "商店街の小さな店を閉める最後の一週間。常連と店主のあいだで起きること",
     ["閉店 最後の日", "商店街 昭和"]),
    ("旅先の出会い", "一人旅・湯治場・夜行バス・フェリーで出会った見知らぬ人と過ごす短い時間",
     ["一人旅 シニア", "湯治 旅"]),
    ("熟年離婚・卒婚", "長い結婚生活の終わりを決めた夫婦の、最後の数日",
     ["熟年離婚 その後", "卒婚"]),
    ("介護の日々", "夫・妻・親を介護する日々の中で、相手の思いがけない言葉や行動に出会う",
     ["老老介護", "介護 夫婦 泣ける"]),
    ("昔の仲間", "還暦や定年で集まった昔の仲間（部活・職場・バンド）。ひとりが隠していた事情が明るみに出る",
     ["還暦 仲間", "昔の仲間 定年"]),
    ("味の記憶", "亡き人の料理、なくなった定食屋の味。その味を再現しようとする人の話",
     ["母の味 レシピ", "定食屋 昭和"]),
    ("新しい恋", "伴侶を亡くした人や独り身の人が、いま目の前の人に惹かれる。過去の恋ではなく今の恋",
     ["シニア恋愛", "70代 恋", "未亡人 恋"]),
    ("初恋・再会", "昔の恋人や初恋の人との再会",
     ["初恋 再会", "同窓会 再会"]),
    ("動物との暮らし", "老いた犬や猫、迷い込んだ動物が、ひとり暮らしの人の毎日を変える",
     ["老犬 介護", "猫 ひとり暮らし 高齢"]),
    ("小さな嘘", "小さな嘘や勘違いが転がって大事になる、くすっと笑えて最後に温かい話",
     ["夫婦 勘違い 笑える", "小さな嘘"]),
    ("故郷じまい", "実家じまい・墓じまいで久しぶりに帰った故郷で起きること",
     ["実家じまい", "墓じまい 故郷"]),
]
KIND_NAMES = [k for k, _, _ in STORY_KINDS]
GENERAL_SEEDS_JA = ["朗読 泣ける", "人生の後半", "昭和 思い出", "老後 生き方"]

STAGES = [("trend", "트렌드 조회"), ("plan", "소재·설계"), ("write", "집필"), ("images", "그림"),
          ("motion", "움직임"), ("voice", "목소리"), ("music", "배경음악"), ("render", "합성"), ("trailer", "예고편"),
          ("pack", "섬네일·업로드 정보")]


# ─────────────────────────────────────────────────────────────────────────────
# 공통
# ─────────────────────────────────────────────────────────────────────────────
def pf(state: dict, *parts) -> str:
    d = os.path.join(state.get("project_dir", "projects/tmp"), "rodoku", *parts[:-1])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, parts[-1])


def keep(keys: dict, state: dict, local: str, name: str, ctype: str = "") -> str:
    if not hz._r2_ok(keys) or not hz.usable(local):
        return ""
    from src import r2_store
    try:
        return r2_store.upload_file(keys, local, f"scenestory/{state.get('project_id', 'tmp')}/{name}", ctype)
    except Exception as e:
        print(f"[rodoku] R2 업로드 실패 {name}: {e}", flush=True)
        return ""


def _claude(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _json_call(api_key: str, system: str, user: str, max_tokens: int = 8000) -> dict:
    from src.prompts import _call_json
    return _call_json(_claude(api_key), system, user, max_tokens=max_tokens)


def _text_call(api_key: str, system: str, user: str, max_tokens: int = 6000) -> str:
    from src.prompts import SCRIPT_MODEL, _text_of
    resp = _claude(api_key).messages.create(model=SCRIPT_MODEL, max_tokens=max_tokens, system=system,
                                            messages=[{"role": "user", "content": user}])
    return _text_of(resp).strip()


def _n(t: str) -> int:
    return len(re.sub(r"\s", "", t or ""))


# ─────────────────────────────────────────────────────────────────────────────
# ① 트렌드
# ─────────────────────────────────────────────────────────────────────────────
def pick_kind(recent_kinds: list, salt: float = 0.0) -> str:
    """최근 6편에 안 쓴 종류 중 하나. 다 썼으면 가장 오래전에 쓴 것."""
    import random
    rnd = random.Random(salt or time.time())
    recent = [k for k in recent_kinds if k in KIND_NAMES][:6]
    fresh = [k for k in KIND_NAMES if k not in recent]
    if fresh:
        return rnd.choice(fresh)
    return recent[-1]


def collect_trends(n_seeds: int = 8, salt: float = 0.0, kind: str = "") -> dict:
    import random
    from concurrent.futures import ThreadPoolExecutor
    from src.seo_keywords import _autocomplete
    rnd = random.Random(salt or time.time())
    kseeds = next((sd for k, _, sd in STORY_KINDS if k == kind), [])
    if kseeds:
        seeds = kseeds + rnd.sample(GENERAL_SEEDS_JA, 2)
    else:
        seeds = rnd.sample(SEEDS_JA, min(n_seeds, len(SEEDS_JA)))
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda s: _autocomplete(s, count=10, hl="ja", gl="JP"), seeds))
    seen, out = set(), []
    for q in [q for lst in res for q in lst]:
        k = "".join(q.split()).lower()
        if k in seen or any(b in q.lower() for b in _BLOCK_JA) or len(k) < 4:
            continue
        seen.add(k)
        out.append(q.strip())
    return {"seeds": seeds, "queries": out[:40], "kind": kind, "at": time.strftime("%Y-%m-%d %H:%M")}


# ─────────────────────────────────────────────────────────────────────────────
# ② 소재·설계
# ─────────────────────────────────────────────────────────────────────────────
PLAN_SYSTEM = """あなたは日本の60〜70代に向けたYouTube「SceneStory 朗読ドラマ」の脚本家です（25年のキャリアを持つ映画・ドラマ作家の感覚で書く）。
実際の検索語リストを受け取り、その中から今週いちばん視聴者の心に刺さる題材をひとつ選び、オリジナル短編の設計図を作ります。
以下のJSONだけを出力してください（説明文・コードブロック記号は禁止）。

{
  "kind": "指定された題材の型（そのまま書く）",
  "picked_query": "選んだ検索語（リストの文言そのまま）",
  "why_ko": "그 검색어를 고른 이유 (한국어 한두 문장)",
  "title_ja": "作品タイトル（12字以内、物・場所・時間が見える言葉。例：閉店の日の豆腐屋、隣の部屋の朝顔、二人分の湯たんぽ）",
  "title_ko": "제목의 한국어 뜻",
  "logline_ja": "一行あらすじ（人物・出来事・秘密が入る）",
  "logline_ko": "한 줄 줄거리 (한국어)",
  "setting": {"place": "具体的な地名・場所", "time": "季節・年代・時刻", "object": "物語を貫く小道具ひとつ"},
  "characters": [{"name": "名前（読み仮名）", "age": 67, "role": "主人公/相手/家族など", "secret": "その人が隠していること"}],
  "young_woman": {"name": "名前（読み仮名）", "age": 24, "role": "孫娘 / 娘 / 若い日の主人公（回想） / 近所の大学生 / 店のアルバイト など、この物語での立場",
                  "look_en": "English. この作品だけの外見を確定的に一文で: hairstyle, one hair accessory, outfit and its colors, one small habit or item she always has"},
  "turn": "物語の反転（後半で明かされる事実）",
  "ending_ja": "最後の一行の方向性",
  "chapters": [
    {"no": 1, "title_ja": "章題（8字以内）", "beat_ko": "이 장에서 일어나는 사건 (한국어, 구체적 장면)",
     "image_prompt": "English. One still scene for this chapter: place, season, light, one object, one figure seen from behind, and the ONE vermilion red accent named in red_accent. Definitive single state.",
     "with_young": true,
     "motion_prompt": "English. この絵の中で小さく繰り返し動くもの2〜3個だけ（例: grass and her hair sway in a soft breeze, clouds drift slowly, light ripples on the water, petals float down）。カメラ・人物の位置・構図は動かさない"}
  ],
  "seo_keywords": ["検索されやすい言葉5〜8個"],
  "red_accent": "English. この物語を貫く『朱色のもの』ひとつ（例: a thin red thread, a red umbrella, a red camellia, a red knitted scarf, a red postbox）",
  "turn_chapter": 4,
  "music": {
    "a": "English. 反転の前（第1章〜反転の直前）に流す劇伴。この物語の場所・時代・季節・感情に合わせる。楽器・テンポ(BPM 56〜76)・ムードを確定的に一文で",
    "b": "English. 反転の章から最後まで流す劇伴。aと同じ世界観で、感情の色を変える（例：秘密が明かされた後の静かな痛み、温かい赦し）"
  }
}

設計ルール
- 主人公は60〜75歳。舞台は日本（昭和の記憶が残る町・駅・喫茶店・団地・温泉など）。実在の有名人・作品名は使わない。
- 題材は指定された「題材の型」に必ず従う。検索語はその型の中で視聴者が何を気にしているかを知る手がかりにする。
- 『〜年ぶり』『〜年越し』『〜年後』のような長い年月の隔たりを売りにするのは「初恋・再会」の型のときだけ。
  それ以外の型では物語の大半を「いま」の数日間で起こし、過去は回想として少しだけにする。
- 手紙・はがき・ノート・日記・写真は、直近の作品で使っていなければ小道具にしてよい（使用禁止リストに入っていたら使わない）。
- 「最近の作品」に挙がったタイトルの言葉、小道具、赤いもの、舞台は今回は使わない。
- 毎回、20代の若い女性（young_woman）をひとり物語に入れる。視聴者が「若い頃の自分」か「自分の娘・孫」を重ねて見る人物。
  作品ごとに別人で、立場も最近の作品と重ねない（孫娘・娘・回想の若い主人公・近所の大学生・店のアルバイト・旅先の若い車掌など）。
  名前・髪型・服もその作品だけのものにする。主人公の人生を動かすきっかけになる役にし、飾りにしない。
- young_woman は「昭和の記憶が残る町に立つ、いまの2020年代の若い女性」。古い町並みの中で彼女だけが今の時代の色を持つ対比を絵の見どころにする。
  look_en には次を必ず確定的に入れる（回想の若い主人公の役なら、その時代の髪型と服にする）:
  ① いまの日本の髪型をひとつ（例: wolf-cut bob with a hidden inner-color layer / hime-cut with blunt side locks /
     asymmetric bob tucked behind one ear / half-up bun with loose strands / one thin side braid in a long bob / micro bangs with a short bob）。
     最近の作品と同じ髪型にしない。
  ② 小さな今の持ち物か装身具をひとつ（例: vintage film camera, silver ear cuff, wireless earbuds, sketchbook, bicycle helmet on her arm）
  ③ 服と色（赤・朱色の服や小物は使わない。赤は red_accent だけ）
- image_prompt の光は場面に合わせてひとつに決めて書く。屋外なら「濃いコバルトブルーの空、金色に縁取られた入道雲、水や濡れた地面に映る空」、
  室内なら「窓から差し込む光の筋、光の中に舞う細かな塵、床に落ちる窓枠の影」。室内の絵に空や湖を入れない。
- with_young はその章の絵に young_woman が映るなら true（全章のうち2〜3章）。その章の image_prompt では彼女の顔が見えてよい。
- 不倫・恋・夫婦の秘密などを扱ってよいが、性的描写・暴力・自死は書かない。読後に温かさか、静かな痛みが残る結末にする。
- 小道具をひとつ決め、第1章で出し、反転で意味を変え、最終章で戻す（例：合鍵、鍋の焦げ跡、将棋の駒、古い腕時計、湯呑み、自転車の鍵、編みかけのセーター）。
- 反転は最後から2番目の章に置く。各章で必ず出来事がひとつ起きる。回想は全体の3割以内。
- image_prompt は人物の顔を描かない（後ろ姿・手・シルエット・遠景の小さな人物）。文字・看板の文字は入れない。
- チャンネルの目印：毎章の絵に red_accent の朱色のものを必ずひとつ入れ、それが画面で唯一の鮮やかな赤になる。
  反転の章ではその赤の意味が変わる置き方にする（例：結ばれていた赤い糸がほどけている、閉じていた赤い傘が開いている）。
- turn_chapter は反転が起きる章の番号。music は歌のない劇伴（instrumental, no vocals）。朗読の邪魔をしない静かな編成にする
  （ピアノ・弦・アコースティックギター・クラリネット・アコーディオンなど。昭和の喫茶店なら古いレコードのような質感なども可）。
  実在の曲名・アーティスト名は書かない。ドラム・電子音・急な盛り上がりは入れない。"""


def make_plan(api_key: str, queries: list, n_chapters: int, made_titles: list, kind: str = "",
              recent: list = None) -> dict:
    kdesc = next((d for k, d, _ in STORY_KINDS if k == kind), "")
    rec = "\n".join(f"- 『{r.get('title', '')}』 型:{r.get('kind', '?')} / 小道具:{r.get('object', '')} / "
                    f"赤:{r.get('red', '')} / 舞台:{r.get('place', '')} / 若い女性の立場:{r.get('young', '')} / 若い女性の外見:{r.get('young_look', '')}" for r in (recent or [])[:8])
    banned = sorted({w for r in (recent or [])[:6] for w in (r.get("object", ""), r.get("red", "")) if w})
    import random
    hero = "女性" if random.random() < 0.7 else "男性"   # 시청자 64% 가 여성 (YouTube 분석, 2026-11)
    user = (f"今回の題材の型（必須）: {kind or '自由'}" + (f" — {kdesc}" if kdesc else "") + "\n"
            f"主人公（視点人物）の性別: {hero}（視聴者の多くは60〜70代の女性。その人が自分のこととして聴ける人物にする）\n\n"
            f"検索語リスト（日本・YouTube自動補完、実際に検索されている言葉）:\n" +
            "\n".join(f"- {q}" for q in queries) +
            f"\n\n章の数: ちょうど {n_chapters} 章\n"
            f"最近の作品（タイトル・小道具・赤いもの・舞台を重ねない）:\n{rec or 'なし'}\n"
            f"使用禁止の小道具・赤いもの: {', '.join(banned) or 'なし'}\n"
            f"ほかに作った作品: {', '.join(made_titles[:20]) or 'なし'}\nJSONのみ出力。")
    plan = _json_call(api_key, PLAN_SYSTEM, user, max_tokens=6000)
    chs = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)][:n_chapters]
    if len(chs) < 3:
        raise ValueError("설계에 장이 부족합니다.")
    for i, c in enumerate(chs):
        c["no"] = i + 1
    plan["chapters"] = chs
    if kind:
        plan["kind"] = kind
    return plan


def recent_plans(keys: dict, skip_pid: str = "") -> list:
    """R2 에 남은 최근 편들의 설계 요약 (최신순). 서버가 재시작돼도 R2 에서 읽으므로 기록이 끊기지 않는다."""
    idx = cloud_index(keys)
    out = []
    for pid in sorted(idx, reverse=True):
        if pid == skip_pid or len(out) >= 8:
            continue
        try:
            pl = (cloud_state(keys, pid).get("plan") or {})
        except Exception:
            continue
        if not pl.get("title_ja"):
            continue
        kind = pl.get("kind", "")
        if not kind and re.search(r"年ぶり|年越し|年後|年分|再会|初恋|同窓会", pl.get("title_ja", "") + pl.get("logline_ja", "")):
            kind = "初恋・再会"   # 종류 기록이 생기기 전 편들은 거의 이 종류였다
        out.append({"title": pl.get("title_ja", ""), "kind": kind,
                    "object": (pl.get("setting") or {}).get("object", ""), "red": pl.get("red_accent", ""),
                    "place": (pl.get("setting") or {}).get("place", ""),
                    "young": (pl.get("young_woman") or {}).get("role", ""),
                    "young_look": (pl.get("young_woman") or {}).get("look_en", "")[:90]})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ③ 집필 — Novel-Engine 규칙 (vendor/novel_prompt.py) 을 일본어 낭독에 맞춰 적용
# ─────────────────────────────────────────────────────────────────────────────
def _novel_rules() -> str:
    try:
        from src.vendor import novel_prompt as N
        blocks = [N.BJND_SCENE_ENFORCER_BLOCK, N.OPENING_MASTERY_BLOCK, N.EVENT_MANDATE_BLOCK,
                  N.BEHAVIORAL_REPETITION_GUARD_BLOCK, N.PARAGRAPH_RHYTHM_BLOCK, N.NARRATIVE_DISTANCE_BLOCK]
        return "\n".join(b.strip() for b in blocks)
    except Exception as e:
        print(f"[rodoku] Novel-Engine 규칙 불러오기 실패: {e}", flush=True)
        return ""


WRITE_SYSTEM_HEAD = """あなたは「SceneStory 朗読ドラマ」の作家です。日本の60〜70代が夜、テレビの前で耳で聴く短編を書きます。
本文だけを出力します（章題・見出し・注釈・記号の説明は書かない）。

[朗読のための日本語]
- 三人称・過去形。地の文はやさしい語彙、一文は短め（40字前後まで）。難しい漢字語は避ける。
- 会話は「」。誰が話したか耳で分かるように、会話の前後に話し手の動作を一つ置く。
- 数字は漢数字（六十七歳、四十五年）。英語・記号・括弧は使わない。
- 感情を説明しない。手・物・音・匂いで見せる。
- 章の最後の一文は、次の章を聴きたくなる一文で終える（最終章は物語の最後の一行）。

[下の作家ルールは韓国語で書かれた原則です。日本語で書くときもこの原則をそのまま守ってください]
"""


def write_chapter(api_key: str, plan: dict, ch: dict, prev_text: str, target_chars: int) -> str:
    system = WRITE_SYSTEM_HEAD + _novel_rules()
    design = {k: plan.get(k) for k in ("title_ja", "logline_ja", "setting", "characters", "young_woman", "turn", "ending_ja")}
    outline = [{"no": c["no"], "title_ja": c.get("title_ja"), "beat": c.get("beat_ko")} for c in plan["chapters"]]
    user = (f"[作品設計]\n{json.dumps(design, ensure_ascii=False)}\n\n[全章の流れ]\n{json.dumps(outline, ensure_ascii=False)}\n\n"
            f"[いま書く章] 第{ch['no']}章「{ch.get('title_ja', '')}」: {ch.get('beat_ko', '')}\n"
            f"[分量] 空白を除いて {int(target_chars * 0.9)}〜{int(target_chars * 1.1)} 字\n\n"
            + (f"[直前の章の終わり]\n{prev_text[-600:]}\n\n" if prev_text else "")
            + "本文だけを書いてください。")
    text = _text_call(api_key, system, user, max_tokens=4000)
    n = _n(text)
    if n < target_chars * 0.75 or n > target_chars * 1.3:
        fix = (user + f"\n\n[前回の原稿 — {n}字。分量が範囲外です。物語はそのままに {target_chars}字前後に整えてください]\n" + text)
        text = _text_call(api_key, system, fix, max_tokens=4000)
    return re.sub(r"^#.*\n", "", text).strip()


# ─────────────────────────────────────────────────────────────────────────────
# ⑥ 합성용 카드
# ─────────────────────────────────────────────────────────────────────────────
def _card_png(out: str, big: str, small: str = "", W: int = 1920, H: int = 1080) -> str:
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SERIF_BOLD, phrase_wrap
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(20, 14, 12, 120))
    f_big = jp_font(JP_SERIF_BOLD, 96)
    lines = phrase_wrap(d, big, f_big, W - 300)[:2]
    lh = 130
    y = H // 2 - (len(lines) * lh) // 2
    if small:
        d.text((W // 2, y - 70), small, font=jp_font(JP_SERIF_BOLD, 40), fill=(227, 181, 164, 255), anchor="ma")
    for i, ln in enumerate(lines):
        d.text((W // 2, y + i * lh), ln, font=f_big, fill=(255, 244, 234, 255), anchor="ma",
               stroke_width=3, stroke_fill=(20, 14, 12, 255))
    img.save(out, "PNG")
    return out


def _card_clip(loop: str, png: str, sec: float, out: str) -> str:
    """루프 영상의 끝 부분(sec 초) + 카드 글자 → 같은 인코딩 규격의 짧은 클립.
    루프 끝에서 잘라 오므로, 뒤에 붙는 본문(루프 처음부터)과 화면이 끊김 없이 이어진다."""
    ld = hz.duration(loop) or float(hz.KB_PERIOD)
    a = max(ld - sec, 0.0)
    fc = (f"[0:v]trim={a:.3f}:{a + sec:.3f},setpts=PTS-STARTPTS[b];[1:v]format=rgba,fade=t=in:st=0:d=0.6:alpha=1,"
          f"fade=t=out:st={sec - 0.6:.2f}:d=0.6:alpha=1[o];[b][o]overlay=0:0,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", loop, "-loop", "1", "-framerate", str(hz.FPS),
                    "-t", f"{sec}", "-i", png, "-filter_complex", fc, "-map", "[v]", *hz.X264, "-crf", "20",
                    "-an", "-t", f"{sec}", out], check=True, timeout=600)
    return out


def _body_clip(loop: str, start: float, sec: float, out: str) -> str:
    """루프를 처음부터 sec 초만큼 스트림 복사로 반복 (다시 인코딩하지 않음). start 는 하위 호환용 — 쓰지 않는다
    (-ss 와 반복을 함께 쓰면 타임스탬프가 겹친다)."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", loop,
                    "-t", f"{sec:.3f}", "-c", "copy", "-an", out], check=True, timeout=600)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ⑦ 예고편
# ─────────────────────────────────────────────────────────────────────────────
TRAILER_SYSTEM = """あなたはYouTubeショートの予告編編集者です。朗読ドラマ本文から、続きを聴きたくなる一節を選びます。
本文の連続した文をそのまま抜き出し（改変しない）、空白を除いて120〜180字。結末のネタばらしはしない。
JSONだけを出力: {"chapter": 章番号, "excerpt": "抜き出した本文", "hook_line": "画面上部に出す8〜14字の問いかけ", "shorts_title": "ショートのタイトル（30字以内、#朗読 と物語の題材に合うハッシュタグ1個を含む。『〜年ぶり』『〜年越し』は本当に年月の隔たりが物語の核のときだけ）"}"""


def _vertical_anime(raw: str, out: str, sec: int = 12) -> str:
    """움직임 클립 → 초당 7.5장 앞뒤 루프 → 9:16 가운데 자르기 → sec 초 길이."""
    one = out.replace(".mp4", "_one.mp4")
    n = max(int(hz.duration(raw) * ANIME_FPS), 4)
    vf = (f"[0:v]fps={ANIME_FPS},split[f][b];[b]reverse,trim=start_frame=1:end_frame={n - 1},setpts=PTS-STARTPTS[r];"
          f"[f][r]concat=n=2:v=1:a=0,fps={hz.FPS},scale=-2:1920,crop=1080:1920,setsar=1,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-filter_complex", vf, "-map", "[v]",
                    *hz.X264, "-crf", "21", "-an", one], check=True, timeout=600)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", one, "-t", f"{sec}",
                    "-c", "copy", out], check=True, timeout=300)
    return out


def _vertical_loop(image: str, out: str, sec: int = 12) -> str:
    n = int(sec * hz.FPS)
    vf = (f"scale=-2:2400,crop=1350:2400,zoompan=z='1+0.015*(1-cos(2*PI*on/{n}))':"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps={hz.FPS},setsar=1,format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(hz.FPS), "-t", f"{sec}",
                    "-i", image, "-vf", vf, "-frames:v", str(n), *hz.X264, "-crf", "21", "-an", out],
                   check=True, timeout=600)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ⑧ 업로드 정보
# ─────────────────────────────────────────────────────────────────────────────
PACK_SYSTEM = """あなたはYouTubeチャンネル「SceneStory」（60〜70代向けオリジナル朗読ドラマ）のアップロード担当です。JSONだけを出力:
{"title": "【朗読ドラマ】で始め、作品タイトルと検索語を自然に入れる（60字以内。例：【朗読ドラマ】閉店の日の豆腐屋｜最後の常連客｜人生の後半）。末尾の言葉は物語の題材に合わせる",
 "description": "3〜5行。あらすじの入口（結末は書かない）、作家オリジナル作品であること、寝る前やお茶の時間にどうぞ、の一言。",
 "tags": ["検索語・ジャンル語 12〜15個"],
 "hashtags": ["#朗読", "#朗読ドラマ", 題材に合う1個]}
誇張・扇情的な表現、性的な言葉は使わない。"""

UPLOAD_SETTINGS = [
    ("카테고리", "エンターテイメント (엔터테인먼트)"),
    ("아동용 여부", "아니요, 아동용이 아닙니다"),
    ("동영상 언어", "일본어"),
    ("변경되거나 합성된 콘텐츠", "AI 음성·AI 그림이 들어가므로 '예'"),
    ("예약", "본편 금요일 21:00 JST · 예고 쇼츠는 본편 하루 전"),
    ("예고 쇼츠", "설명란·고정 댓글에 본편 링크, '관련 동영상'에 본편 연결"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 전체 작업
# ─────────────────────────────────────────────────────────────────────────────
# ── 그림체: 단순하고 따뜻한 손그림 인물 + 빛나는 정밀 배경(하늘·구름·빛·반사) + 장마다 단 하나의 주홍색 (채널 표식) ──
ART_PREFIX = (
    "Contemporary Japanese animated feature film still, refined modern character design: slender realistic "
    "proportions, delicate fine linework, detailed eyes with soft catchlights, natural small nose and lips, soft "
    "gradient cel shading on skin, individually rendered hair strands with glossy light sheen. Hyper-detailed "
    "luminous painted background with glowing light, golden highlights, soft lens flare and tiny drifting light "
    "particles, lived-in nostalgic Showa-era Japan details, wide cinematic 16:9 composition."
)
ART_SUFFIX = (
    " The vermilion red object is the only red in the whole image. "
    "Elderly people are seen from behind, in silhouette or small in the distance, with no facial features. "
    "No text, no letters, no numbers, no signboard writing."
)

CLOUD_INDEX = "scenestory/_index.json"


def save_cloud(keys: dict, state: dict) -> None:
    """서버가 재시작돼도 작업이 사라지지 않게 상태 JSON 을 R2 에 함께 둔다."""
    if not hz._r2_ok(keys):
        return
    from src import r2_store
    pid = state.get("project_id", "")
    try:
        r2_store.put_json(keys, f"scenestory/{pid}/state.json", state)
        idx = r2_store.get_json(keys, CLOUD_INDEX) or {}
        row = {"title": (state.get("plan") or {}).get("title_ja") or state.get("title", ""),
               "stage": state.get("stage", ""), "at": time.strftime("%Y-%m-%d %H:%M")}
        if idx.get(pid) != row:
            idx[pid] = row
            r2_store.put_json(keys, CLOUD_INDEX, idx)
    except Exception as e:
        print(f"[rodoku] R2 상태 저장 실패: {e}", flush=True)


def cloud_index(keys: dict) -> dict:
    if not hz._r2_ok(keys):
        return {}
    from src import r2_store
    try:
        return r2_store.get_json(keys, CLOUD_INDEX) or {}
    except Exception:
        return {}


def cloud_state(keys: dict, pid: str) -> dict:
    from src import r2_store
    return r2_store.get_json(keys, f"scenestory/{pid}/state.json") or {}


def _rss_mb() -> int:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def start_auto(state: dict, keys: dict, save_fn, made_titles: list) -> bool:
    def save_both(s):
        save_fn(s)
        save_cloud(keys, s)
    return hz._start(state["project_id"], "rodoku", "낭독 드라마 자동 제작", _worker,
                     (state, keys, save_both, list(made_titles)))


def _stage(job, state, save_fn, key, i, msg=""):
    job["msg"] = f"[{i + 1}/{len(STAGES)}] {dict(STAGES)[key]}" + (f" · {msg}" if msg else "")
    job["pct"] = i / len(STAGES)
    state["stage"] = key
    state["status"] = dict(STAGES)[key]
    print(f"[rodoku] {state.get('project_id', '')} {job['msg']} · 메모리 {_rss_mb()}MB", flush=True)
    hz._save(save_fn, state)
    if job.get("stop"):
        raise RuntimeError("중지했습니다. '이어서 만들기'를 누르면 여기서부터 계속합니다.")


def _worker(job, state, keys, save_fn, made_titles):
    ak = keys.get("ANTHROPIC_API_KEY", "")
    minutes = int(state.get("minutes", DEFAULT_MIN))
    n_ch = LENGTHS.get(minutes, LENGTHS[DEFAULT_MIN])["chapters"]

    # ① 이야기 종류 고르기 → 그 종류의 검색어로 트렌드
    recent = state.get("_recent") if "_recent" in state else None
    if not (state.get("trend") or {}).get("queries"):
        _stage(job, state, save_fn, "trend", 0)
        recent = recent_plans(keys, state.get("project_id", ""))
        state["_recent"] = recent
        kind = pick_kind([r.get("kind", "") for r in recent])
        tr = collect_trends(kind=kind)
        if not tr["queries"]:
            tr["queries"] = next((sd for k, _, sd in STORY_KINDS if k == kind), ["シニア 朗読"])
            tr["fallback"] = True
        state["trend"] = tr

    # ② 설계
    if not (state.get("plan") or {}).get("chapters"):
        _stage(job, state, save_fn, "plan", 1, "검색어에서 소재를 고르는 중")
        if recent is None:
            recent = recent_plans(keys, state.get("project_id", ""))
        plan = make_plan(ak, state["trend"]["queries"], n_ch, made_titles,
                         kind=(state.get("trend") or {}).get("kind", ""), recent=recent)
        state["plan"] = plan
        state["title"] = f"{plan.get('title_ja', '')} ({plan.get('title_ko', '')})"
        state["topic"] = f"{plan.get('title_ja', '')} · {plan.get('title_ko', '')}"
        state["chapters"] = [{"no": c["no"], "title_ja": c.get("title_ja", ""), "beat_ko": c.get("beat_ko", ""),
                              "image_prompt": c.get("image_prompt", ""),
                              "motion_prompt": c.get("motion_prompt", ""),
                              "with_young": bool(c.get("with_young"))} for c in plan["chapters"]]
    plan, chs = state["plan"], state["chapters"]

    # ③ 집필
    total_chars = minutes * 60 * JA_CPS - (OPEN_CARD_SEC + len(chs) * (CHAPTER_PAD_SEC + 2)) * JA_CPS
    per = int(total_chars / len(chs))
    prev = ""
    for c in chs:
        if not c.get("text"):
            _stage(job, state, save_fn, "write", 2, f"제{c['no']}장 「{c['title_ja']}」 쓰는 중")
            c["text"] = write_chapter(ak, plan, c, prev, per)
            c["chars"] = _n(c["text"])
        prev = c["text"]
    state["manuscript_chars"] = sum(c.get("chars", 0) for c in chs)

    # ④ 그림
    for c in chs:
        img = c.setdefault("image", {})
        if not hz.ensure_local(keys, img, pf(state, f"ch{c['no']:02d}.jpg")):
            _stage(job, state, save_fn, "images", 3, f"제{c['no']}장 그림")
            body = c["image_prompt"].strip().rstrip(".") + "."
            if "red" not in body.lower():   # 예전 설계엔 주홍색 지정이 없다 → 기본값을 넣는다
                body += f" {(plan.get('red_accent') or 'A thin red thread').strip().rstrip('.')} in vivid vermilion red."
            yw = plan.get("young_woman") or {}
            if c.get("with_young") and yw.get("look_en"):
                body += (f" The young Japanese woman in her twenties: {yw['look_en'].strip().rstrip('.')}. "
                         "Her face is visible.")
            prompt = ART_PREFIX + " " + body + ART_SUFFIX
            url = hz.generate_image(keys.get("REPLICATE_API_TOKEN", ""), prompt)
            dest = pf(state, f"ch{c['no']:02d}.jpg")
            hz._download(url, dest)
            img.update(local=dest, r2_key=keep(keys, state, dest, f"ch{c['no']:02d}.jpg", "image/jpeg"))
            hz._save(save_fn, state)

    # ④-2 움직임 — 장마다 6초 움직임 클립 (실패한 장은 Ken Burns 로 대신)
    _make_motion(job, state, keys, save_fn)

    # ⑤ 목소리
    from src.audio import generate_narration
    voice = keys.get("ELEVENLABS_VOICE_ID_JA") or JA_VOICE_ID
    kanji = "一二三四五六七八九十"
    for c in chs:
        au = c.setdefault("audio", {})
        if not hz.ensure_local(keys, au, pf(state, f"ch{c['no']:02d}.mp3")):
            _stage(job, state, save_fn, "voice", 5, f"제{c['no']}장 낭독")
            dest = pf(state, f"ch{c['no']:02d}.mp3")
            head = f"第{kanji[c['no'] - 1] if c['no'] <= 10 else c['no']}章、{c['title_ja']}。\n\n"
            info = {}
            generate_narration(keys.get("ELEVENLABS_API_KEY", ""), head + c["text"], dest, voice_id=voice, info=info)
            au.update(local=dest, seconds=round(hz.duration(dest), 2), model=info.get("model", ""),
                      r2_key=keep(keys, state, dest, f"ch{c['no']:02d}.mp3", "audio/mpeg"))
            hz._save(save_fn, state)

    # ⑤-2 배경음악 — 편마다 이야기에 맞춰 새로 2곡 (반전 전 / 반전 후)
    _make_music(job, state, keys, save_fn)

    # ⑥ 합성
    if not hz.usable((state.get("final") or {}).get("local", "")) and not (state.get("final") or {}).get("r2_key"):
        _stage(job, state, save_fn, "render", 7, "화면 루프 만드는 중")
        _render(job, state, keys, save_fn)

    # ⑦ 예고편
    if not (state.get("trailer") or {}).get("local"):
        _stage(job, state, save_fn, "trailer", 8, "예고 쇼츠 만드는 중")
        try:
            _trailer(job, state, keys)
        except Exception as e:
            state["trailer"] = {"error": f"{type(e).__name__}: {e}"[:300]}
            print(f"[rodoku] 예고편 실패: {e}", flush=True)
        hz._save(save_fn, state)

    # ⑧ 섬네일·업로드 정보
    _stage(job, state, save_fn, "pack", 9)
    _pack(state, keys)
    state["stage"] = "done"
    state["status"] = "완성"
    hz._save(save_fn, state)
    fin = state["final"]
    job["msg"], job["pct"] = f"완성 — {hz.fmt_time(fin['seconds'], True)} · {fin['bytes'] / 1e6:.0f}MB", 1.0


MUSIC_TAIL = (" Instrumental only, no vocals, no drums. Quiet and intimate, it sits softly under a Japanese "
              "voice-over, no sudden swells, gentle natural ending. About three minutes long.")
MUSIC_FALLBACK = {
    "a": "Gentle cinematic solo piano with soft strings, nostalgic and tender, slow 66 BPM, warm evening mood.",
    "b": "Solo piano with a single cello, bittersweet and quietly hopeful, slow 62 BPM, the feeling after a long-kept secret is told.",
}


def _make_music(job, state, keys, save_fn):
    """설계의 music.a / music.b 로 이 편 전용 배경음악 2곡 (각 3분). 실패한 곡은 건너뛴다 — 음악 없이도 합성은 된다."""
    music = (state.get("plan") or {}).get("music") or {}
    bgm = state.setdefault("bgm", {})
    for kind in ("a", "b"):
        it = bgm.setdefault(kind, {})
        dest = pf(state, "music", f"bgm_{kind}.mp3")
        if hz.ensure_local(keys, it, dest):
            continue
        it.pop("error", None)   # 지난번 실패한 곡은 이어서 만들기 때 다시 시도
        _stage(job, state, save_fn, "music", 6, f"{'반전 전' if kind == 'a' else '반전 후'} 곡 만드는 중 (ElevenLabs Music 3분)")
        prompt = (music.get(kind) or MUSIC_FALLBACK[kind]).strip().rstrip(".") + "." + MUSIC_TAIL
        try:
            hz._gen_elevenlabs(keys.get("ELEVENLABS_API_KEY", ""), prompt, 180, dest)
            it.update(local=dest, prompt=prompt, seconds=round(hz.duration(dest), 2),
                      r2_key=keep(keys, state, dest, f"bgm_{kind}.mp3", "audio/mpeg"))
        except Exception as e:
            it["error"] = f"{type(e).__name__}: {e}"[:300]
            print(f"[rodoku] 배경음악 {kind} 실패: {e}", flush=True)
        hz._save(save_fn, state)


MOTION_FALLBACK = ("grass and clothes sway gently in a soft breeze, clouds drift slowly, "
                   "light shimmers softly on the water, tiny light particles float")
ANIME_FPS = 7.5   # 손그림 애니메이션처럼 초당 7.5장 (30프레임 영상에서 한 장을 4프레임씩 고르게 보여 준다)


def _make_motion(job, state, keys, save_fn):
    """그림 한 장 → MiniMax 6초 움직임 클립. state['motion_on'] 이 False 면 건너뛴다(Ken Burns)."""
    if state.get("motion_on") is False:
        return
    from src.video_replicate import generate_single_clip_url
    for c in state["chapters"]:
        mo = c.setdefault("motion", {})
        if hz.ensure_local(keys, mo, pf(state, f"ch{c['no']:02d}_motion.mp4")):
            continue
        img = hz.ensure_local(keys, c.get("image") or {}, pf(state, f"ch{c['no']:02d}.jpg"))
        if not img:
            continue
        mo.pop("error", None)   # 지난번 실패한 장은 이어서 만들기 때 다시 시도
        _stage(job, state, save_fn, "motion", 4, f"제{c['no']}장 움직임 (MiniMax 6초, 보통 2~5분)")
        prompt = ((c.get("motion_prompt") or MOTION_FALLBACK).strip().rstrip(".") +
                  ". Static locked-off camera, no camera movement, no zoom, no pan, no cuts. The people stay in "
                  "place, only the small repeating elements move. Keep the hand-drawn animation look. No text.")
        dest = pf(state, f"ch{c['no']:02d}_motion.mp4")
        try:
            url = generate_single_clip_url(keys.get("REPLICATE_API_TOKEN", ""), prompt, image_url=img,
                                           prompt_optimizer=False)
            hz._download(url, dest)
            mo.update(local=dest, prompt=prompt,
                      r2_key=keep(keys, state, dest, f"ch{c['no']:02d}_motion.mp4", "video/mp4"))
        except Exception as e:
            mo["error"] = f"{type(e).__name__}: {e}"[:300]
            print(f"[rodoku] 제{c['no']}장 움직임 실패 → Ken Burns: {e}", flush=True)
        hz._save(save_fn, state)


def build_anime_loop(raw: str, out: str) -> str:
    """6초 움직임 클립 → 초당 7.5장으로 줄여 손그림 애니메이션 느낌 → 앞으로+거꾸로 이어 끊김 없는 약 12초 루프."""
    n = max(int(hz.duration(raw) * ANIME_FPS), 4)
    vf = (f"[0:v]fps={ANIME_FPS},split[f][b];[b]reverse,trim=start_frame=1:end_frame={n - 1},setpts=PTS-STARTPTS[r];"
          f"[f][r]concat=n=2:v=1:a=0,fps={hz.FPS},{hz.FILL},format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-filter_complex", vf, "-map", "[v]",
                    *hz.X264, "-crf", "20", "-an", "-movflags", "+faststart", out], check=True, timeout=900)
    return out


def _render(job, state, keys, save_fn):
    chs = state["chapters"]
    segs, audio_parts, marks = [], [], []
    # 오프닝 카드 (1장 그림 · 작품 제목)
    loops = {}
    for c in chs:
        raw = hz.ensure_local(keys, c.get("motion") or {}, pf(state, f"ch{c['no']:02d}_motion.mp4"))
        lp = pf(state, "work", f"loop{c['no']:02d}{'_anime' if raw else ''}.mp4")
        if not hz.usable(lp):
            job["msg"] = f"[8/10] 합성 · 제{c['no']}장 화면 루프 ({'움직임' if raw else 'Ken Burns'})"
            if raw:
                try:
                    build_anime_loop(raw, lp)
                except Exception as e:
                    print(f"[rodoku] 제{c['no']}장 움직임 루프 실패 → Ken Burns: {e}", flush=True)
                    lp = pf(state, "work", f"loop{c['no']:02d}.mp4")
            if not hz.usable(lp):
                hz.build_kenburns_loop(c["image"]["local"], lp)
        loops[c["no"]] = lp
    title = state["plan"].get("title_ja", "")
    op = _card_clip(loops[1], _card_png(pf(state, "work", "open.png"), title, "SceneStory 朗読ドラマ"),
                    OPEN_CARD_SEC, pf(state, "work", "seg_open.mp4"))
    segs.append(op)
    audio_parts.append(("silence", OPEN_CARD_SEC))
    t = OPEN_CARD_SEC
    kanji = "一二三四五六七八九十"
    for c in chs:
        job["msg"] = f"[8/10] 합성 · 제{c['no']}장 이어 붙이는 중"
        a = c["audio"]["seconds"] or hz.duration(c["audio"]["local"])
        seg_len = a + CHAPTER_PAD_SEC
        card = _card_png(pf(state, "work", f"t{c['no']:02d}.png"), c["title_ja"],
                         f"第{kanji[c['no'] - 1] if c['no'] <= 10 else c['no']}章")
        segs.append(_card_clip(loops[c["no"]], card, TITLE_CARD_SEC, pf(state, "work", f"seg{c['no']:02d}a.mp4")))
        segs.append(_body_clip(loops[c["no"]], TITLE_CARD_SEC, max(seg_len - TITLE_CARD_SEC, 0.5),
                               pf(state, "work", f"seg{c['no']:02d}b.mp4")))
        marks.append((t, f"第{kanji[c['no'] - 1] if c['no'] <= 10 else c['no']}章 {c['title_ja']}"))
        audio_parts.append(("file", c["audio"]["local"]))
        audio_parts.append(("silence", CHAPTER_PAD_SEC))
        t += max(seg_len, TITLE_CARD_SEC + 0.5)
    total = t
    lst = pf(state, "work", "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"file '{os.path.abspath(s)}'\n")
    video = pf(state, "work", "video.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", video],
                   check=True, timeout=900)
    # 낭독 트랙
    args, labels = [], []
    k = 0
    for kind, val in audio_parts:
        if kind == "silence":
            args += ["-f", "lavfi", "-t", f"{val}", "-i", "anullsrc=r=44100:cl=stereo"]
        else:
            args += ["-i", val]
        labels.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo[s{k}]")
        k += 1
    fc = ";".join(labels) + ";" + "".join(f"[s{i}]" for i in range(k)) + f"concat=n={k}:v=0:a=1[narr]"
    # 배경음악: 반전 전 곡(a) → 반전 장 제목 카드에서 3초 크로스페이드 → 반전 후 곡(b). 각 곡은 필요한 만큼 반복
    bg = state.get("bgm") or {}
    ga = bg.get("a", {}).get("local") if hz.usable(bg.get("a", {}).get("local", "")) else ""
    gb = bg.get("b", {}).get("local") if hz.usable(bg.get("b", {}).get("local", "")) else ""
    try:
        turn_no = int((state.get("plan") or {}).get("turn_chapter") or 0)
    except (TypeError, ValueError):
        turn_no = 0
    turn_no = turn_no if 2 <= turn_no <= len(chs) else max(len(chs) - 1, 2)
    t_turn = next((a for (a, _), c in zip(marks, chs) if c["no"] == turn_no), total * 0.65)
    fade = f"volume={BGM_VOLUME},afade=t=in:d=3,afade=t=out:st={max(total - 5, 0):.2f}:d=5"
    if ga and gb:
        args += ["-stream_loop", "-1", "-i", ga, "-stream_loop", "-1", "-i", gb]
        fc += (f";[{k}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{t_turn + 3:.2f}[ba]"
               f";[{k + 1}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{max(total - t_turn + 3, 4):.2f}[bb]"
               f";[ba][bb]acrossfade=d=3:c1=tri:c2=tri,{fade}[bg]")
    elif ga or gb:
        args += ["-stream_loop", "-1", "-i", ga or gb]
        fc += f";[{k}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total + 1:.2f},{fade}[bg]"
    if ga or gb:
        fc += ";[narr][bg]amix=inputs=2:duration=first:normalize=0[mx]"
        out_label = "[mx]"
    else:
        out_label = "[narr]"
    audio = pf(state, "work", "audio.m4a")
    hz._run_ffmpeg([*args, "-filter_complex", fc + f";{out_label}loudnorm=I=-16:TP=-1.5:LRA=11[a]", "-map", "[a]",
                    "-t", f"{total:.2f}", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", audio], total, job, "[8/10] 합성 · 소리")
    final = pf(state, f"SceneStory_{state['project_id']}.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio, "-map", "0:v:0", "-map", "1:a:0",
                    "-c", "copy", "-t", f"{total:.2f}", "-movflags", "+faststart", final], check=True, timeout=900)
    info = {"local": final, "seconds": round(hz.duration(final), 2), "bytes": os.path.getsize(final),
            "chapters": [[round(a, 2), b] for a, b in marks], "made_at": time.strftime("%Y-%m-%d %H:%M")}
    job["msg"] = f"[8/10] 합성 · R2 에 올리는 중 ({info['bytes'] / 1e6:.0f}MB)"
    info["r2_key"] = keep(keys, state, final, os.path.basename(final), "video/mp4")
    state["final"] = info
    hz._save(save_fn, state)


def _trailer(job, state, keys):
    from src.audio import generate_narration
    from src import captions as cap
    from src.assembler import render_scene_clip
    chs = state["chapters"]
    full = "\n\n".join(f"第{c['no']}章\n{c['text']}" for c in chs[:-1])     # 마지막 장(결말)은 빼고 고른다
    pick = _json_call(keys.get("ANTHROPIC_API_KEY", ""), TRAILER_SYSTEM, full, max_tokens=1500)
    excerpt = (pick.get("excerpt") or "").strip()
    if not excerpt:
        raise ValueError("예고 대목을 고르지 못했습니다.")
    no = int(pick.get("chapter") or 1)
    c = next((x for x in chs if x["no"] == no), chs[0])
    voice = keys.get("ELEVENLABS_VOICE_ID_JA") or JA_VOICE_ID
    au = pf(state, "trailer", "voice.mp3")
    generate_narration(keys.get("ELEVENLABS_API_KEY", ""), excerpt, au, voice_id=voice)
    sec = min(hz.duration(au) + 1.5, 58.0)
    tmp = pf(state, "trailer", "x").rsplit("/", 1)[0]
    raw = hz.ensure_local(keys, c.get("motion") or {}, pf(state, f"ch{c['no']:02d}_motion.mp4"))
    vloop = ""
    if raw:
        try:
            vloop = _vertical_anime(raw, os.path.join(tmp, "vloop.mp4"), sec=int(sec) + 1)
        except Exception as e:
            print(f"[rodoku] 예고편 움직임 실패 → Ken Burns: {e}", flush=True)
    if not vloop:
        vloop = _vertical_loop(c["image"]["local"], os.path.join(tmp, "vloop.mp4"), sec=int(sec) + 1)
    top = os.path.join(tmp, "top.png")
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SERIF_BOLD, JP_SANS_BOLD
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((540, 150), "SceneStory 朗読ドラマ", font=jp_font(JP_SERIF_BOLD, 40), fill=(227, 181, 164, 255), anchor="ma",
           stroke_width=3, stroke_fill=(20, 14, 12, 255))
    d.text((540, 230), pick.get("hook_line") or state["plan"].get("title_ja", ""), font=jp_font(JP_SANS_BOLD, 76),
           fill=(255, 244, 234, 255), anchor="ma", stroke_width=6, stroke_fill=(20, 14, 12, 255))
    d.text((540, 1780), "続きは本編で", font=jp_font(JP_SANS_BOLD, 48), fill=(227, 181, 164, 255), anchor="ma",
           stroke_width=4, stroke_fill=(20, 14, 12, 255))
    im.save(top)
    caps = cap.build_for_scene({"narration": excerpt}, sec, tmp, 1, 1080, 1920, lang="ja", instant=True)
    silent = os.path.join(tmp, "v.mp4")
    render_scene_clip(vloop, top, sec, silent, instant=True, captions=caps, punch_in=False)
    out = pf(state, "trailer", "trailer.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", au, "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-t", f"{sec:.2f}",
                    "-movflags", "+faststart", out], check=True, timeout=600)
    state["trailer"] = {"local": out, "seconds": round(sec, 1), "chapter": no, "excerpt": excerpt,
                        "hook_line": pick.get("hook_line", ""), "shorts_title": pick.get("shorts_title", ""),
                        "r2_key": keep(keys, state, out, "trailer.mp4", "video/mp4")}


def _pack(state, keys):
    plan, fin = state["plan"], state["final"]
    # 섬네일 (HASIRA 섬네일 함수 재사용 · 1장 그림)
    proxy = {"project_id": state["project_id"], "project_dir": state["project_dir"],
             "image": next((c["image"] for c in state["chapters"] if c.get("with_young") and (c.get("image") or {}).get("local")),
                           state["chapters"][0]["image"]), "thumbnail": {}}
    try:
        hz.make_thumbnail(keys, proxy, plan.get("title_ja", ""), "SCENESTORY · 朗読ドラマ", brand="SceneStory")
        th = proxy["thumbnail"]
        state["thumbnail"] = {"local": th.get("local", ""), "r2_key": keep(keys, state, th.get("local", ""),
                                                                           "thumbnail.jpg", "image/jpeg")}
    except Exception as e:
        state["thumbnail"] = {"error": str(e)[:200]}
    pack = {"title": f"【朗読ドラマ】{plan.get('title_ja', '')}｜{plan.get('kind') or '人生の後半'}",
            "description": plan.get("logline_ja", ""),
            "tags": plan.get("seo_keywords") or [], "hashtags": ["#朗読", "#朗読ドラマ", "#人生の後半"]}
    try:
        user = (f"作品: {plan.get('title_ja')}\nあらすじ: {plan.get('logline_ja')}\n検索語: {plan.get('picked_query')}\n"
                f"SEO語: {', '.join(plan.get('seo_keywords') or [])}\n長さ: {hz.fmt_time(fin['seconds'], True)}")
        pack.update({k: v for k, v in _json_call(keys.get("ANTHROPIC_API_KEY", ""), PACK_SYSTEM, user, 1500).items() if v})
    except Exception as e:
        print(f"[rodoku] 업로드 정보 생성 실패 → 기본값: {e}", flush=True)
    chs = [(0.0, "オープニング")] + [(a, b) for a, b in fin.get("chapters", [])]
    body = (pack.get("description") or "").strip()
    body += "\n\n― 目次 ―\n" + hz.chapter_text(chs, fin["seconds"])
    body += "\n\n脚本家が書き下ろしたオリジナル短編です。登場人物・団体は架空のものです。"
    hts = [h if str(h).startswith("#") else f"#{h}" for h in (pack.get("hashtags") or [])][:3]
    if hts:
        body += "\n\n" + " ".join(hts)
    pack["full_description"] = body
    tags = [str(t).strip().lstrip("#") for t in pack.get("tags") or [] if str(t).strip()]
    while tags and len(",".join(tags)) > 480:
        tags.pop()
    pack["tags"] = tags
    state["upload_pack"] = pack


def link(keys: dict, item: dict) -> str:
    if not item or not item.get("r2_key") or not hz._r2_ok(keys):
        return ""
    from src import r2_store
    return r2_store.download_link(keys, item["r2_key"], filename=os.path.basename(item["r2_key"]))
