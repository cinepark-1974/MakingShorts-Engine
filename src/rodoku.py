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

import datetime as dt
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
    ("介護の日々", "遠くに住む親や夫・妻を介護する日々の中で、相手の思いがけない言葉や行動に出会う",
     ["親の介護 50代", "遠距離介護", "介護 夫婦 泣ける"]),
    ("昔の仲間", "還暦や定年で集まった昔の仲間（部活・職場・バンド）。ひとりが隠していた事情が明るみに出る",
     ["還暦 仲間", "昔の仲間 定年"]),
    ("味の記憶", "亡き人の料理、なくなった定食屋の味。その味を再現しようとする人の話",
     ["母の味 レシピ", "定食屋 昭和"]),
    ("新しい恋", "伴侶を亡くした人や独り身の人が、いま目の前の人に惹かれる。過去の恋ではなく今の恋",
     ["50代 恋愛", "シニア恋愛", "未亡人 恋"]),
    ("初恋・再会", "昔の恋人や初恋の人との再会",
     ["初恋 再会", "同窓会 再会"]),
    ("動物との暮らし", "老いた犬や猫、迷い込んだ動物が、ひとり暮らしの人の毎日を変える",
     ["老犬 介護", "猫 ひとり暮らし 高齢"]),
    ("小さな嘘", "小さな嘘や勘違いが転がって大事になる、くすっと笑えて最後に温かい話",
     ["夫婦 勘違い 笑える", "小さな嘘"]),
    ("夫の不可解な行動", "最近、夫の様子がおかしい（早朝に出かける・知らない匂い・減っていくお金・知らない女性からの電話）。疑いが深まった末に、温かい真実がわかる",
     ["夫 怪しい 行動", "夫 隠し事", "定年前 夫"]),
    ("子の巣立ち", "子どもが家を出て、急に静かになった家。残された夫婦か母が、空いた部屋で思いがけない物や気持ちに出会う",
     ["子供 巣立ち 寂しい", "空の巣症候群", "子離れ"]),
    ("母と娘", "年老いた母と、五十代になった娘。言えずにきた本音が、ある出来事でこぼれる",
     ["母と娘 確執", "実家の母 本音"]),
    ("パートの職場", "子育てを終えて久しぶりに働き始めた職場（スーパー・食堂・クリーニング店など）で、思いがけない人や秘密に出会う",
     ["50代 パート", "50代 再就職"]),
    ("スカッと・息子夫婦", "主人公を「お荷物」「老後はひとりで」と見下し、家やお金を当てにする息子夫婦。主人公は黙って準備を進め、最後に品よく、きっぱりと形勢を逆転する",
     ["スカッとする話 息子夫婦", "スカッと 嫁 義母", "スカッと 朗読"]),
    ("スカッと・義家族", "嫁いでから長年、義母・義姉に見下されてきた主人公。ある出来事をきっかけに、隠してきた事実と主人公の本当の力が明らかになる",
     ["スカッとする話 義母", "スカッと 義姉", "嫁いびり スカッと"]),
    ("スカッと・夫と浮気相手", "主人公を「何もできない妻」と侮る夫と、その相手。主人公は静かに証拠と生活の準備を整え、最後に立場が逆転する",
     ["スカッとする話 夫 浮気", "スカッと 離婚 朗読"]),
    ("スカッと・見下す人々", "パート先の上司・ママ友・近所の人に年齢や身なりで見下される主人公。実は誰も知らなかった経歴や人脈が明らかになり、相手が青ざめる",
     ["スカッとする話 パート", "スカッと 見下し 逆転"]),
    ("スカッと・身分逆転", "質素に暮らす主人公を「貧乏」「年金暮らし」「田舎者」と見下し、お金を当てにする家族や相手。実は主人公には誰も知らない資産や経歴"
     "（亡き夫から継いだ不動産、元校長、地元企業の大株主など）があり、相手の欲と本性が露わになったところで静かに明かされる",
     ["スカッとする話 資産", "スカッと 年金暮らし 見下し", "スカッと 貧乏 逆転"]),
    ("スカッと・相続", "親の葬儀や四十九日のあと、家・土地・預金を独り占めしようとする兄弟や親族。介護を一人で担ってきた主人公は黙っているが、"
     "遺言書（公正証書）・名義・生前の記録が明かされ、欲張った側が自分の言葉で立場を失う",
     ["スカッとする話 相続", "遺産 兄弟 揉める", "介護したのに 相続"]),
    ("スカッと・老後資金", "主人公の年金・貯金・退職金を当てにする子どもや夫。「どうせ使い道がない」と勝手に使おうとするが、主人公はお金の流れを静かに押さえていて、"
     "最後に通帳と契約書の一枚で形勢が変わる",
     ["スカッと 年金 当てにする", "老後資金 子供 たかる", "退職金 夫 勝手に"]),
    ("故郷じまい", "実家じまい・墓じまいで久しぶりに帰った故郷で起きること",
     ["実家じまい", "墓じまい 故郷"]),
]
KIND_NAMES = [k for k, _, _ in STORY_KINDS]

# 화자의 앞말 '형식' 36가지 — 엔진이 최근 10편에 안 쓴 형식을 무작위로 고르고, 문장은 Claude 가 그 편 이야기로 새로 쓴다.
# (완성 문장 1000개를 미리 만들어 두면 이야기와 상관없는 말이 붙고, 형식은 결국 반복된다)
INTRO_FORMS = [
    "告白: 誰かが一度だけ打ち明けてくれた話として始める",
    "場面: 語り手が覚えている、ある日の一場面の描写で始める",
    "物: 引き出し・箱・ポケットから出てきた一つの物で始める",
    "問い: 聴く人に向けた静かな問いかけで始める",
    "音: ある音（踏切、ラジオ、風鈴、雨どい）の記憶で始める",
    "匂い: ある匂い（煮物、石けん、古い本）の記憶で始める",
    "味: ある料理やお菓子の味の記憶で始める",
    "季節: 季節の変わり目の一日で始める",
    "天気: その日の天気と空の色で始める",
    "時刻: 具体的な時刻（午前四時、終電の後）で始める",
    "日付: 何年何月何日という日付で始める",
    "言葉: 誰かが言った一言の引用で始める",
    "嘘: 語り手が長いあいだ信じていた小さな嘘で始める",
    "後悔: 語り手が言えなかった一言で始める",
    "約束: 守られなかった、あるいは守られた約束で始める",
    "手紙以外の記録: 家計簿・回覧板・レシート・メモ書きで始める",
    "写真ではなく絵: 誰かが描いた絵やらくがきで始める",
    "場所の今: その場所が今どうなっているかで始める",
    "癖: 登場人物の小さな癖で始める",
    "手: 誰かの手の様子で始める",
    "背中: 誰かの後ろ姿の記憶で始める",
    "電話: 一本の電話（留守電、間違い電話）で始める",
    "道: いつも通った道や坂で始める",
    "乗り物: バス・電車・自転車の思い出で始める",
    "動物: 一匹の犬や猫や鳥で始める",
    "植物: 庭木・鉢植え・道端の花で始める",
    "数字: ある数（三十年、七回、二人分）で始める",
    "比べる: 昔と今の小さな違いで始める",
    "秘密の場所: 誰にも教えなかった場所で始める",
    "夢: 語り手が見た夢で始める",
    "気づき: 大人になって初めて分かったことで始める",
    "噂: 町で聞いた噂で始める",
    "最後: 何かの最後の日（閉店、引っ越し、卒業）で始める",
    "最初: 何かを初めてした日で始める",
    "沈黙: 誰も何も言わなかった時間で始める",
    "名前: ある名前の由来や呼び方で始める",
]
GENERAL_SEEDS_JA = ["朗読 泣ける", "人生の後半", "昭和 思い出", "平成 思い出", "80年代 思い出", "老後 生き方"]

# 주인공 1958~1974년생의 젊은 날 = 1975~2004년 (쇼와 50년대 ~ 헤이세이 10년대 초)
ERA_PAST = [
    ("昭和50年代（1975〜1984）", "喫茶店、カセットテープ、ラジカセ、公衆電話、文通、国鉄の駅、団地の新築"),
    ("昭和の終わり（1985〜1989）", "ディスコ、肩パッドのスーツ、社員旅行、テレホンカード、深夜のタクシー、寿退社"),
    ("平成初め（1989〜1994）", "トレンディドラマの夜、ポケベル、ワープロ、レンタルビデオ店、カラオケボックス"),
    ("平成10年頃（1995〜1999）", "PHS、CDショップ、使い捨てカメラ、プリクラ、ルーズソックス、就職氷河期"),
    ("平成10年代のはじめ（2000〜2004）", "折りたたみ携帯、写メール、着メロ、MD、ネットカフェ、ミレニアムの年越し"),
]

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
def pick_kind(recent_kinds: list, salt: float = 0.0, group: str = "") -> str:
    """최근 6편에 안 쓴 종류 중 하나. 다 썼으면 가장 오래전에 쓴 것.
    group: 'naku'·'koi'·'natsu'·'suka' 를 주면 그 재생목록(감동·사랑·추억·통쾌편)의 종류 안에서만 고른다."""
    import random
    rnd = random.Random(salt or time.time())
    if group in PLAYLISTS:
        pool = [k for k in KIND_NAMES if _playlist_key({"kind": k}) == group]
        recent = [k for k in recent_kinds if k in pool][:max(len(pool) - 1, 0)]
        return rnd.choice([k for k in pool if k not in recent] or pool)
    recent = [k for k in recent_kinds if k in KIND_NAMES][:6]
    fresh = [k for k in KIND_NAMES if k not in recent]
    if not fresh:
        return recent[-1]
    sk = [k for k in fresh if is_sukatto(k)]
    if sk and rnd.random() < SUKATTO_SHARE:     # 시니어 낭독에서 가장 큰 장르 — 10편 중 7편
        return rnd.choice(sk)
    rest = [k for k in fresh if not is_sukatto(k)] or fresh
    return rnd.choice(rest)


SUKATTO_SHARE = 0.7   # 2026-11-14: 돈·상속·역전 편의 클릭과 시청 유지가 높음 → 10편 중 7편


def is_sukatto(kind: str) -> bool:
    return str(kind or "").startswith("スカッと")


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
PLAN_SYSTEM = """あなたは日本の50〜70代の女性に向けたYouTube「SceneStory 朗読ドラマ」の脚本家です（25年のキャリアを持つ映画・ドラマ作家の感覚で書く）。
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
  "heroine": {"name": "主人公の名前（読み仮名）", "age": 56, "look_en": "English. 主人公（50代の女性）のアニメ風の外見を確定的に一文で: a chic hairstyle of an elegant woman in her mid-fifties with a few silver strands (e.g. a short layered bob with soft waves / shoulder-length soft waves tucked behind one ear / an elegant low chignon — never long girlish hair), a slender refined face (clear bright eyes, faint laugh lines at the eye corners), a slim graceful figure, a tasteful outfit of her generation and its colors (e.g. fine-knit cardigan over a blouse, camel coat, wide slacks or a long pleated skirt, no red), one small everyday item"},
  "characters": [{"name": "名前（読み仮名）", "age": 58, "role": "主人公/相手/家族など", "secret": "その人が隠していること"}],
  "young_woman": {"name": "名前（読み仮名）", "age": 24, "role": "孫娘 / 娘 / 若い日の主人公（回想） / 近所の大学生 / 店のアルバイト など、この物語での立場",
                  "look_en": "English. この作品だけの外見を確定的に一文で: hairstyle, one hair accessory, outfit and its colors, one small habit or item she always has"},
  "narrator_intro": "第一章の前に語り手（young_woman）が一人称で語る前置き。1〜2文、空白を除いて25〜60字",
  "cover_chapter": 2,
  "cover_scene": "English. サムネイル・ショート表紙専用の屋外の昼の一場面。この物語の舞台の地域らしい屋外の景色（その土地の道・川・海・坂・並木・駅など）で、指定された季節と天気と光の下。暗くしない、明るい昼。主人公（heroine、50代）がひとり立つか歩き、red_accent の朱色の物を持つか身につける。顔が見え、物語の謎を胸に抱えた表情（遠くを見つめる・小さく息をのむ）。一つの状態・一つの動作で確定的に書く",
  "turn": "物語の反転（後半で明かされる事実）",
  "core": {"loss_or_lack": "喪失|欠如", "wound_event": "主人公の傷を一つの出来事で（いつ・どこで・誰が・何を）", "goal": "主人公が望む具体的なもの（名詞）",
           "need": "本人は気づいていない本当に必要なもの", "strategy_first": "物語の始めの主人公のやり方", "strategy_last": "結末で変わったやり方"},
  "plants": [{"what": "伏線（物・台詞・習慣。具体的に）", "plant_ch": 1, "payoff_ch": 5, "meaning": "回収で変わる意味"}],
  "ally": "クライマックスで主人公の側に立つ人物と、その場にいる理由（前の章で用意しておく。偶然にしない）",
  "settlement": "結末で、お金・名義・家・関係がどう決着したか（具体的に。スカッと以外は空でよい）",
  "short_lines": [{"role": "blow", "ch": 1, "line": "主人公が受ける一撃の台詞（見下す言葉・突き放す宣告・残酷な事実。「」付き25字以内）"},
                  {"role": "turn", "ch": 4, "line": "形勢が変わる瞬間の一文（隠していた物・事実が出る。台詞か短い地の文、40字以内）"},
                  {"role": "last", "ch": 6, "line": "最後に主人公が言う品のある一言（「」付き25字以内。勝ち誇らない）"}],
  "ending_ja": "最後の一行の方向性",
  "chapters": [
    {"no": 1, "title_ja": "章題（8字以内）", "beat_ko": "이 장에서 일어나는 사건 (한국어, 구체적 장면)",
     "question": "この章の終わりに聴き手が抱く問い（日本語一文。次の章を聴かずにいられない問い）",
     "image_prompt": "English. One still scene for this chapter: place, season, light, one object, the heroine (face visible, one clear expression) or one figure seen from behind, and the ONE vermilion red accent named in red_accent. Definitive single state.",
     "with_hero": true,
     "with_young": false,
     "ambience_en": "English. この章の場面の環境音を一文で（例: gentle rain on a tin roof with a distant railway crossing bell / summer cicadas and a wind chime on a veranda / quiet waves on a pebble beach）。人の声・音楽は入れない",
     "motion_prompt": "English. この絵の中で小さく繰り返し動くもの2〜3個だけ（例: grass and her hair sway in a soft breeze, clouds drift slowly, light ripples on the water, petals float down）。カメラ・人物の位置・構図は動かさない。手・指・腕は動かさない（髪・服・草・光・水・雲などだけ）",
     "more_scenes": [
       {"image_prompt": "English. 同じ章の後半の別の一場面（机や棚に置かれた小道具の寄り、別の場所、時間の経過など。手のアップは描かない）。image_prompt と同じ書き方", "motion_prompt": "English", "with_hero": false, "with_young": false},
       {"image_prompt": "English. 章の終わりの一場面", "motion_prompt": "English", "with_hero": true, "with_young": false}
     ]}
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
- 主人公は50〜60歳の女性（1966〜1976年生まれ）（視聴者の中心と同じ世代。子どもの巣立ち・親の介護・夫の定年前後・パート勤めなど、いまの暮らしの真ん中にいる人）。
  夫・昔の恋人・兄弟などの男性は相手役として出してよいが、視点人物にはしない。「いま」（2020年代）の数日間が物語の軸。舞台は日本の町・駅・喫茶店・団地・温泉など。
- 物語の始め方（必須）: 第1章は「いま、主人公の身のまわりで起きている小さな謎」から始める（例：夫が毎朝四時に出かける／知らない番号から毎晩電話がある／
  亡き母の口座から毎月同じ額が引き出されている／空き家のはずの実家に灯りがつく）。聴き手が「なぜ？」と思う謎を第1章の最初の数行で出し、
  章を追うごとに疑いを深め、反転の章で温かい真実か静かな痛みの真実を明かす。回想はその謎の答えに近づくためにだけ挟む。
- ただし題材の型が「スカッと・…」のときは次の形にする（謎の形より優先）:
  第1章の最初の数行で、相手が主人公を見下す決定的な一言（台詞）を出す（例：「老後はひとりで暮らしてね」「何もできないくせに」）。
  中盤は主人公が黙って耐えながら、相手の知らない準備・事実を積み重ねる（聴き手にだけ少しずつ見せる）。
  反転の章で事実が明るみに出て、相手の立場が一気に崩れる。主人公は怒鳴らない・暴力も復讐の言葉も使わない。
  最後の一言は品よく短く、聴き手が胸のすく台詞にする。結末で主人公は自分の暮らしを取り戻し、穏やかに前を向く。
  犯罪・暴力・性的な場面・実在の団体や人物は出さない。
  スカッとの組み立て（よく聴かれている作品の構造）:
  ① 屈辱のはしご: 相手の見下しは二度、だんだん強くなる（一度目は小さな侮辱、二度目は決定的な一言）。主人公は毎回静かに受け流し、聴き手の怒りだけが溜まる。反撃は物語の六割を過ぎてから。
  ② 対比の人物: 主人公にやさしい人（もう一人の嫁・孫・近所の人など）を置き、その人は目に見える形で報われる。その報いを知った相手の嫉妬や欲が、相手を自滅の場へ引き寄せる（偶然ではなく因果で対決が起きる）。
  ③ 明かされる事実には伏線を: 相手が序盤に口にした何気ない一言や、主人公の質素な暮らしの描写が、後で意味を変える。
  ④ 相手が自分の口で本音（欲・嘘）をさらす場面を作り、それを ally が聞く・録音が残る、などで決定打にする。ally がその場にいる理由は前の章で用意する。
  ⑤ 夫（または息子）が誰の味方か必ず決め、その立場が動く瞬間を一場面で書く（視聴者がいちばん反応する点）。
  ⑥ お金・相続・年金・名義・離婚の手続きは日本の実際の制度と常識に合わせる（例: 公正証書遺言、年金分割、財産分与、退職金は数週間後に振り込まれる、本人確認なしに大金は下ろせない）。
     聴き手は自分の暮らしで知っているので、現実とずれると冷める。金額は日本の常識の範囲で具体的に（結婚祝いに百万円は非常識、など）。
  ⑦ 結末では settlement（お金・家・関係がどう決着したか）を一場面で示し、相手のその後を短く添える。勝ったあとの主人公の品のよい小さな親切を一つ入れる（相手を見捨てない・やるべきことはする）。
  ⑧ 第1章の冒頭の出来事や無礼な人物は、最終章で回収する（首尾呼応）。
- SceneStory らしさ（よくあるスカッと朗読との違い。2026-11-13 視聴者の不満の調査から）:
  ・嘘くさくしない: パトカー・警察・救急車が都合よく現れる、大勢の前で土下座、相手が逮捕・破産・失踪で破滅、のような作り話くさい決着は使わない。
    決着は日本の制度と人間関係の中で起きる（遺言書、名義、通帳、録音、本人が口にした言葉、第三者の証言）。聴き手が「うちでも起こりうる」と思える大きさにする。
  ・悪役にも一つだけ理由を置く（老後の不安、見栄、寂しさ、昔の傷）。主人公は最後にそれに気づく一行を持つ。単なる悪人の成敗で終わらせない。
  ・結末は「スカッと＋じんわり」: 勝ったあと、相手との距離を主人公が自分で決める（許す、または静かに離れる）。最後はその後の暮らしの小さな場面（台所、庭、駅のホーム）で終える。
  ・毎回、物語の鍵になる「物」と「場所」と「職業」を前の作品と変える（過去作の一覧と重ねない）。
- 過去（回想）は主人公が20〜30代だった頃（若い恋の頃、子育ての頃、働き盛りの頃）。主人公の年齢は時代と矛盾させない。ユーザー文で指定される時代を使い、その時代の具体的な物・音・言葉を一つ以上入れる。
  昭和30〜40年代（戦後・高度成長期の初め）は使わない。視聴者自身の若い頃と重なる時代にする。
- 「バブル」という言葉はタイトル・本文・画面の言葉に使わない（派手さや崩壊の苦い記憶を連想させるため）。時代は「昭和の終わり」「平成のはじめ」と呼ぶ。
- 実在の有名人・曲名・ドラマ名・商品名は使わない（時代の空気は「トレンディドラマの夜」「ポケベルの数字」のように一般名詞で出す）。
- 題材は指定された「題材の型」に必ず従う。検索語はその型の中で視聴者が何を気にしているかを知る手がかりにする。
- 『〜年ぶり』『〜年越し』『〜年後』のような長い年月の隔たりを売りにするのは「初恋・再会」の型のときだけ。
  それ以外の型では物語の大半を「いま」の数日間で起こし、過去は回想として少しだけにする。
- 手紙・はがき・置き手紙・遺書・ノート・日記・交換日記・メモ帳・カードは、物語の鍵にも題名にも使わない（2026-11-14: 過去作で使いすぎ、視聴者が離れた）。
  「〜通の手紙」「届かなかった手紙」「日記に書かれていた」のような題・展開は禁止。真実は人の口・行動・お金や名義の記録（通帳・登記・契約書・領収書・録音）・場所で明かす。
- 「最近の作品」に挙がったタイトルの言葉、小道具、赤いもの、舞台は今回は使わない。
- 毎回、20代の若い女性（young_woman）をひとり物語に入れる（脇役。主人公の娘・回想の若い主人公・職場の若い同僚など）。視聴者が「若い頃の自分」か「自分の娘」を重ねて見る人物。
  作品ごとに別人で、立場も最近の作品と重ねない（孫娘・娘・回想の若い主人公・近所の大学生・店のアルバイト・旅先の若い車掌など）。
  名前・髪型・服もその作品だけのものにする。主人公の人生を動かすきっかけになる役にし、飾りにしない。
- young_woman は「昭和・平成の面影が残る町に立つ、いまの2020年代の若い女性」。古い町並みの中で彼女だけが今の時代の色を持つ対比を絵の見どころにする。
  look_en には次を必ず確定的に入れる（回想の若い主人公の役なら、その時代の髪型と服にする）:
  ① いまの日本の髪型をひとつ（例: wolf-cut bob with a hidden inner-color layer / hime-cut with blunt side locks /
     asymmetric bob tucked behind one ear / half-up bun with loose strands / one thin side braid in a long bob / micro bangs with a short bob /
     loose messy updo bun with long side-swept bangs, wispy face-framing strands and a small fresh flower pinned above one ear）。
     髪型に合う顔立ちも一文で決める（例: 無造作なお団子＋流した前髪なら soft oval face with a gently tapered chin, calm almond-shaped eyes, straight soft brows）。
     最近の作品と同じ髪型にしない。
  ② 小さな今の持ち物か装身具をひとつ（例: vintage film camera, silver ear cuff, wireless earbuds, sketchbook, bicycle helmet on her arm）
  ③ 服と色（赤・朱色の服や小物は使わない。赤は red_accent だけ）
- image_prompt には場面の年代を必ず英語で書く（例: "Present day 2026," / "Flashback, Tokyo 1989,"）。過去の場面はその時代の服・髪型・物で描く。
- image_prompt の光は場面に合わせてひとつに決めて書く。屋外なら「濃いコバルトブルーの空、金色に縁取られた入道雲、水や濡れた地面に映る空」、
  室内なら「窓から差し込む光の筋、光の中に舞う細かな塵、床に落ちる窓枠の影」。室内の絵に空や湖を入れない。
- narrator_intro: 朗読の声は30代前半の女性。昔の物語を若い声が語る理由を、毎回 young_woman の立場から一言で作る。
  型はユーザー文で指定される。例（言い回しは毎回変える）:
    告白型「祖母が亡くなる前の晩、一度だけ話してくれたことがあります。」
    場面型「あの豆腐屋のシャッターが、最後に下りた日のことを覚えています。」
    物から入る型「母の鏡台の引き出しに、片方だけの手袋が入っていました。」
    問いかけ型「人は、四十年も同じ嘘をつき続けられるものでしょうか。」
  「最近の作品」の前置きと同じ書き出し・同じ型にしない。「これは〜の話です」で始めない。結末は明かさない。
- cover_chapter: サムネイルにする章の番号。その章は必ず屋外の明るい昼で、物語の舞台の地域らしい景色と、指定された季節・天気・光にする
  （雪の日・雨上がり・紅葉・桜・夏の入道雲・夕方の金色の光など）。主人公が顔の見える姿で映る（with_hero: true）。室内や夜の章を cover_chapter にしない。
- more_scenes: 各章の絵は image_prompt（章の始まり）＋ more_scenes 2つ（章の中ほど・章の終わり）の3枚。朗読の流れに沿って
  場面が変わるように、引きの絵 → 寄りの絵（主人公の表情、または置かれた小道具の大写し。手のアップは描かない）→ 別の場所や時間の絵、のように画角と内容を変える。同じ構図を繰り返さない。
- with_young はその章の絵に young_woman が映るなら true（全章のうち1〜2章）。その章の image_prompt では彼女の顔が見えてよい。
- 不倫・恋・夫婦の秘密などを扱ってよいが、性的描写・暴力・自死は書かない。読後に温かさか、静かな痛みが残る結末にする。
- 小道具をひとつ決め、第1章で出し、反転で意味を変え、最終章で戻す（例：合鍵、鍋の焦げ跡、将棋の駒、古い腕時計、湯呑み、自転車の鍵、編みかけのセーター）。
- 反転は最後から2番目の章に置く。各章で必ず出来事がひとつ起きる。回想は全体の3割以内。
- 主人公（heroine）は絵の中心。with_hero: true の絵では heroine.look_en の姿で、顔と表情が見えてよい（各章のうち少なくとも1枚）。
  70歳以上の人物（主人公の親など）は顔を描かない（後ろ姿・シルエット・遠景の小さな人物）。文字・看板の文字は入れない。
- チャンネルの目印：毎章の絵に red_accent の朱色のものを必ずひとつ入れ、それが画面で唯一の鮮やかな赤になる。
  反転の章ではその赤の意味が変わる置き方にする（例：結ばれていた赤い糸がほどけている、閉じていた赤い傘が開いている）。
- turn_chapter は反転が起きる章の番号。music は歌のない劇伴（instrumental, no vocals）。朗読の邪魔をしない静かな編成にする
  （ピアノ・弦・アコースティックギター・クラリネット・アコーディオンなど。昭和の喫茶店なら古いレコードのような質感なども可）。
  実在の曲名・アーティスト名は書かない。ドラム・電子音・急な盛り上がりは入れない。

物語の骨格（BLUE JEANS の作家エンジンの方法を短編に縮めたもの）
- 6章のときの役目: 1 日常の中の欠如と、最初の謎か侮辱（フック） / 2 事件と、もう後戻りできない主人公の選択 / 3 中盤の偽りの勝利か偽りの敗北（状況のルールが変わる） /
  4 すべてを失う。まだ反撃しない（敗北を知るだけ） / 5 クライマックス。主人公が自分で決めて自分で動き、状況を戻れない形で変える。4章で失ったものが武器になる / 6 結末と余韻。第1章の場面と対比させる。
  章の数が違うときもこの順番を保ち、近い役目をまとめる。
- core: 主人公の傷は説明ではなく出来事で（「寂しい人だった」は不可、「七歳の春、母が台所で倒れた」は可）。結末は strategy_first から strategy_last への変化で見せる。
- plants: 伏線を3つ。plant_ch は1〜3章に散らし、payoff_ch はクライマックスか結末。名前のある人物・物はすべて回収する。植えていない答えで解決しない。同じ章で植えて回収しない。
- 各章に question（聴き手の開いた問い）を一つ。前の章の問いには部分的にだけ答え、より大きな問いを開く。
- クライマックスは主人公の行動で決まる。偶然・第三者・見つめるだけ・気づくだけで解決しない。
- 型ごとの組み立て: スカッとは上の組み立て。感動・恋・懐かしい話は、ユーザー文の「この作品の組み立て」に必ず従う。
- 感情のいちばん高い場面は抑えすぎない（抑制は爆発のあとの余韻であって、爆発がないことではない）。"""


# ── 표지·이야기의 지역과 계절 (2026-11 작가 요청: 파란 하늘만 계속은 단조롭다 → 지역·실제 계절·날씨로 바꾼다) ──
REGIONS = [
    # (일본어 이름, 영어 풍경 단서, 눈이 오는 지역인가)
    ("北海道・小樽", "Otaru in Hokkaido: an old stone canal with gas lamps, brick warehouses, wide open northern sky", True),
    ("北海道・富良野", "Furano in Hokkaido: rolling hills, a lone tree on the slope, big northern sky", True),
    ("東北・盛岡", "Morioka in Tohoku: a river town with a stone bridge, distant mountains", True),
    ("北陸・金沢", "Kanazawa: an old teahouse street with wooden lattices and tiled roofs", True),
    ("信州・松本", "Matsumoto in Nagano: apple orchards and the Northern Alps on the horizon", True),
    ("東京・下町", "an old Tokyo shitamachi neighborhood: a narrow lane, a small shrine, a riverside embankment", False),
    ("鎌倉・湘南", "Kamakura and the Shonan coast: a small seaside railway crossing, the sea beyond", False),
    ("京都", "a quiet Kyoto lane: stone paving, machiya townhouses, a temple gate", False),
    ("尾道・瀬戸内", "Onomichi on the Seto Inland Sea: a hillside town of stone steps overlooking calm islands", False),
    ("長崎", "Nagasaki: a hillside port town with stone slopes and the harbor below", False),
    ("高知・四万十", "the Shimanto River in Kochi: a low sinking bridge over a clear green river", False),
    ("沖縄", "Okinawa: an emerald sea, red-tiled roofs with shisa lions, hibiscus and stone walls", False),
]
# 지역 → 그 지역 말 (2026-11-08: 가나자와 이야기에 간사이 사투리 「信じられへん」이 섞인 문제)
DIALECTS = {"北海道・小樽": "北海道弁", "北海道・富良野": "北海道弁", "東北・盛岡": "盛岡弁", "北陸・金沢": "金沢弁",
            "信州・松本": "松本の言葉（信州弁）", "東京・下町": "東京の下町言葉", "鎌倉・湘南": "標準語（方言は使わない）",
            "京都": "京ことば", "尾道・瀬戸内": "備後弁（尾道）", "長崎": "長崎弁", "高知・四万十": "幡多弁（土佐の言葉）",
            "沖縄": "沖縄の言葉（ウチナーヤマトグチ）"}


def dialect_rule(region: str) -> str:
    name = DIALECTS.get(region or "", "")
    if not name:
        return ""
    kansai = "" if region == "京都" else "関西弁（〜へん・〜やん・〜や・ほんま・あかん・〜はる）は一言も使わない。"
    return (f"[土地の言葉] 舞台は{region}。土地の生まれの人物が混ぜてよいのは{name}だけ。"
            f"ほかの地方の方言は混ぜない。{kansai}自信のない方言の言い回しは使わず、標準語にする。\n")


_SEASON = {1: "真冬", 2: "冬の終わり", 3: "早春", 4: "桜の季節", 5: "新緑", 6: "梅雨", 7: "盛夏", 8: "晩夏",
           9: "初秋", 10: "秋", 11: "晩秋", 12: "初冬"}


def _weathers(month: int, snowy: bool, region: str) -> list:
    """그 달·그 지역에 실제로 있을 날씨만 (오키나와에 눈 없음). 표지는 모두 밝은 낮."""
    out = [("clear", "bright clear daytime sky")]
    if month in (12, 1, 2) and snowy:
        out += [("snow", "a bright snowy day, soft white snow falling, snow on roofs and branches, pale blue sky breaking through")] * 2
    elif month in (12, 1, 2):
        out += [("winter_sun", "a crisp bright winter day, low golden sunlight, clear cold air")]
    if month == 4 and region != "沖縄":
        out += [("sakura", "cherry blossoms in full bloom, petals drifting in bright spring light")] * 2
    if month in (6, 7) or (month in (5,) and region == "沖縄"):
        out += [("after_rain", "just after the rain, wet stone glistening, puddles reflecting a bright sky, hydrangeas")] * 2
    if month in (10, 11) and region != "沖縄":
        out += [("autumn", "brilliant red and gold autumn leaves under a high clear autumn sky")] * 2
    if month in (3, 5, 9, 10, 11):
        out += [("soft_rain", "a soft drizzle under a pale pearl-gray overcast sky glowing with diffused silver light (no blue sky), she holds an open transparent umbrella above her head, glistening wet reflections on the ground")]
    if month in (7, 8, 9) or region == "沖縄":
        out += [("summer", "a vivid summer day, towering white cumulus clouds in a deep blue sky")]
    out += [("golden", "late afternoon golden light, long soft shadows, warm glowing sky")]
    return out


def pick_place_weather(recent_regions: list, month: int = 0, salt: float = 0.0) -> dict:
    """최근 5편에 안 쓴 지역 + 지금 달 + 그 지역에 맞는 날씨."""
    import random
    rnd = random.Random(salt or time.time())
    month = month or (dt.datetime.utcnow() + dt.timedelta(hours=9)).month
    used = [r for r in recent_regions if r][:5]
    pool = [r for r in REGIONS if r[0] not in used] or REGIONS
    name, scene, snowy = rnd.choice(pool)
    wkey, wen = rnd.choice(_weathers(month, snowy, name))
    return {"region": name, "region_en": scene, "month": month, "season": _SEASON[month], "weather": wkey, "weather_en": wen}


# ── 장르별 조립법 (통쾌편 8개 장치와 같은 수준으로, 감동·사랑·추억도 각자의 엔진을 갖게) ──
# 출처: Creator-Engine 대체 골격(관계 아크)·Idea-Engine 상실/결핍·Shortform-Engine 감성 숏폼(Sweet 2 → Bitter 1)·우리 채널 성적(古時計·再会 쇼츠)
GENRE_BUILD = {
    "naku": """感動（夫婦・家族）の組み立て:
  ① 疑いの積み上げ: 主人公は相手（夫・母・義母・子）の不可解な行動を悪く受け取り、聴き手も一緒に疑う。証拠は章ごとに一段ずつ増える（二〜三段階）。
  ② 真実は相手の不器用な愛か、言えずにきた痛み。その手がかりは序盤から置いておく（相手の小さな癖・いつもの物・言いかけてやめた一言）。病気や余命を真実にしない（使い古されている）。
  ③ 相手が言葉にできなかった理由を、相手の人生の出来事として一つ用意する（説明ではなく出来事）。
  ④ 涙の頂点は、相手が直接気持ちを語る場面ではなく、物や行動で主人公が真実を知る瞬間に置く。その直前の章で二人の関係はいちばん冷える（温度差）。
  ⑤ クライマックスは主人公の行動: 今度は主人公の方から伝える・迎えに行く・同じことをし返す。
  ⑥ 首尾呼応: 第1章の不可解な行動を、結末では主人公が（あるいは二人で）する。
  ⑦ 誰も悪者にしない。温かさか、静かな痛みが残る。""",
    "koi": """恋（初恋・再会・大人の恋）の組み立て:
  ① 章ごとに二人の距離が必ず変わる（近づく・離れる・すれ違う）。同じ距離の章を作らない。
  ② 二人を隔てる壁を二種類以上重ねる（時間・家族・立場・主人公自身の心）。壁は章を追って一段ずつ高くなる。
  ③ 中盤で偽りの勝利（ぐっと近づく）→ 秘密や誤解が明るみに出て、いちばん遠く離れる。
  ④ クライマックスは主人公が守りを下ろす行動で、何かを代償に払う（自分から会いに行く・何十年も言えなかった一言を言う・持っていた物を手放す）。
  ⑤ 気持ちは言葉より物と行動で。台詞はずらす（「元気だった？」「ご飯、食べた？」）。告白の一言は一度だけ、いちばん高い場面で。
  ⑥ 主人公の今の人生（夫・家族・亡き伴侶）を否定しない。悪者にしない。過去の恋は今の人生を照らすものとして描く。
  ⑦ 結末は結ばれるか、会って別れて前を向くか。どちらでも、最後の場面は二人の間の小さな物か約束で閉じる。年数（四十年ぶり等）を物語の芯の数字にする。""",
    "natsu": """懐かしい話（昭和・平成の思い出）の組み立て:
  ① いまの喪失が期限になる（店が閉まるまで七日、実家の引き渡しまで三日、取り壊しの前の晩）。期限を第1章で示す。
  ② 過去への扉は具体的な物・音・味・匂い（その時代のものを三つ以上）。説明ではなく、物に触れた瞬間に回想が始まる。
  ③ 謎は昔の誰かの「やり残し」（返せなかった物・言えなかった礼・果たせなかった約束）。主人公はそれを探す。
  ④ 中盤で記憶違いか知らなかった事実が出て、懐かしい過去の意味が変わる（美しいだけの思い出にしない、苦い一点を入れる）。
  ⑤ クライマックスは主人公が過去と今をつなぐ行動（味を再現して振る舞う・仲間を集める・物を本来の持ち主に返す）。
  ⑥ 結末: 失うものは失う。けれど何かが次の世代（young_woman）に手渡される。
  ⑦ 昔を美化しすぎず、今を否定しない。""",
}


def genre_build(kind: str) -> str:
    if is_sukatto(kind):
        return ""            # 통쾌편 조립법은 PLAN_SYSTEM 안에 있다
    return GENRE_BUILD.get(_KIND_PLAYLIST.get(kind, "naku"), "")


# ── 소재 후보 3개 → 엄격한 편집자 채점 → 1위로 설계 (Idea-Engine 의 HUNTER 시드 3안 + TRIAGE Hook 5축·Story Core 5원칙) ──
SEED_SYSTEM = """あなたは日本の50〜70代の女性に向けた朗読ドラマの企画者です（25年のキャリアを持つ映画・ドラマ作家の感覚で考える）。
今回の題材の型と手がかりから、短編（約15分）の「種」を3つ作ります。3つは路線を変える:
 安全 = この型で実証済みの形を、いちばん強い一場面で磨く / 変主 = 実証済みの形を一か所だけ裏切る / 挑戦 = 視聴者がまだ見ていない題材や視点。
各種の条件:
- 主人公は50〜60歳の女性。具体的な名詞の目的を持つ（「幸せになりたい」ではなく「夫の退職金で開く小さな店」）。
- 欠如（最初からなかったもの）か喪失（奪われた・失ったもの）かを決め、その傷を一つの出来事として書く（いつ・どこで・誰が・何を）。
- 第1章の最初の数行で起きる出来事を一行で（謎か、主人公を見下す決定的な台詞）。
- 結末の型を決める: 逆転（立場がひっくり返る）/ 気づき（本当のことを知る）/ 和解 / 告白 / 別れ。結末が決まらない種は出さない。
- お金・年数・年齢は具体的な数字で（例: 月六万五千円の年金、退職金三千万円、四十年）。数字は日本の暮らしの常識に合わせる。
- 手紙・はがき・日記・ノート・遺書・置き手紙を鍵にした種は出さない（使い古しで視聴者が離れた）。真実は人の口・行動・通帳や名義・契約・録音・場所で明かす。
- 実在の人物・団体・商品名は使わない。犯罪・暴力・性的な場面は使わない。
JSONのみ: {"seeds": [{"lane": "安全|変主|挑戦", "title_ja": "12字以内", "logline_ja": "主人公は〜を望むが、〜のせいで〜を失いかける（一文）",
 "first_event": "第1章冒頭の出来事", "loss_or_lack": "喪失|欠如", "wound_event": "傷の出来事", "goal": "具体的な目的",
 "turn": "反転", "ending_type": "逆転|気づき|和解|告白|別れ", "ending_ja": "最後の場面", "numbers": "使う数字", "why_now": "視聴者の暮らしとの接点"}]}"""

SCORE_SYSTEM = """あなたは朗読ドラマの企画を判定する厳しい編集者です。書いた人とは別人として、点数を甘くしない（迷ったら低い方）。
各種を次の10項目で0〜10点で採点する。
[フック5軸] specificity（すぐ映像が浮かぶ固有の一場面か。100回見た題材は0）/ conflict（対立が一行で見えるか）/ genre（型の約束が明確か）/
stakes（失うものの大きさ・外と内と関係）/ originality（最近の作品・よくある形と違うか）
[物語の芯5原則] empathy（50〜70代の女性が自分のこととして聴けるか）/ desire（目的が具体的な名詞か）/ calibration（難しいが可能な障害か）/
impact（一週間覚えている一場面があるか）/ ending（結末の型が決まっていて満足できるか）
減点: 最近の作品と主人公の型・題材が重なる（originality を下げる）。お金・法律・手続きが日本の現実とずれている（calibration を下げる）。
JSONのみ: {"scores": [{"lane": "...", "hook": {"specificity": 0, "conflict": 0, "genre": 0, "stakes": 0, "originality": 0},
 "core": {"empathy": 0, "desire": 0, "calibration": 0, "impact": 0, "ending": 0}, "weak": "7点未満の軸ごとの具体的な補強案（日本語、なければ空）"}]}"""


def pick_seed(api_key: str, kind: str, kdesc: str, queries: list, viral: str, recent_txt: str, perf: str = "") -> dict:
    """소재 후보 3개를 만들고 채점해 1위를 고른다. 1위의 훅 점수가 35 미만이면 한 번 다시 만든다. 실패하면 {} (예전 방식으로 설계)."""
    def _sum(d):
        try:
            return sum(int(v) for v in (d or {}).values())
        except Exception:
            return 0
    tries = []
    feedback = ""
    for attempt in range(2):
        user = (f"題材の型: {kind or '自由'}" + (f" — {kdesc}" if kdesc else "") + "\n"
                + (genre_build(kind) + "\n" if genre_build(kind) else "")
                + (viral + "\n" if viral else "") + (perf + "\n" if perf else "")
                + "検索語（実際に検索されている言葉）:\n" + "\n".join(f"- {q}" for q in queries[:20])
                + f"\nこれまでの作品（題材・商売・小道具の組み合わせを重ねない）:\n{recent_txt or 'なし'}\n" + (f"\n[前回の種の弱点 — 今回は避ける]\n{feedback}\n" if feedback else ""))
        seeds = [x for x in (_json_call(api_key, SEED_SYSTEM, user, 7000).get("seeds") or []) if isinstance(x, dict)][:3]
        if not seeds:
            break
        sc = _json_call(api_key, SCORE_SYSTEM, "題材の型: " + (kind or "自由") + f"\n最近の作品:\n{recent_txt or 'なし'}\n\n[種]\n"
                        + json.dumps(seeds, ensure_ascii=False), 3000).get("scores") or []
        for i, sd in enumerate(seeds):
            r = sc[i] if i < len(sc) and isinstance(sc[i], dict) else {}
            sd["hook_score"], sd["core_score"] = _sum(r.get("hook")), _sum(r.get("core"))
            sd["score_detail"] = {"hook": r.get("hook"), "core": r.get("core")}
            sd["weak"] = r.get("weak", "")
        tries.append({"seeds": [dict(x) for x in seeds],
                      "best": max(seeds, key=lambda x: x["hook_score"] + x["core_score"]).get("title_ja", "")})
        # 복사본에만 tries 를 붙인다 — 원본(seeds 안의 dict)에 붙이면 자기 자신을 품는 순환 참조가 되어 상태 저장이 실패한다 (2026-11-08 무한 반복 원인)
        best = dict(max(seeds, key=lambda x: x["hook_score"] + x["core_score"]))
        if best["hook_score"] >= 35 or attempt == 1:
            best["tries"] = tries
            return best
        feedback = "\n".join(f"- 『{x.get('title_ja', '')}』 フック{x['hook_score']}/50: {x.get('weak', '')}" for x in seeds)
    return {}


def seed_prompt(seed: dict) -> str:
    """고른 소재를 설계 단계에 넘기는 문장."""
    if not seed:
        return ""
    keys = ("title_ja", "logline_ja", "first_event", "loss_or_lack", "wound_event", "goal", "turn", "ending_type", "ending_ja", "numbers")
    body = "\n".join(f"  {k}: {seed.get(k, '')}" for k in keys if seed.get(k))
    return ("今回の種（編集会議で選ばれた企画。必ずこの種で設計する。題名は磨いてよい）:\n" + body
            + (f"\n  補強すること: {seed['weak']}" if seed.get("weak") else "") + "\n")


def make_plan(api_key: str, queries: list, n_chapters: int, made_titles: list, kind: str = "",
              recent: list = None, viral: str = "", seed: dict = None, archive: str = "") -> dict:
    import random
    kdesc = next((d for k, d, _ in STORY_KINDS if k == kind), "")
    rec = "\n".join(f"- 『{r.get('title', '')}』 型:{r.get('kind', '?')} / 小道具:{r.get('object', '')} / "
                    f"赤:{r.get('red', '')} / 舞台:{r.get('place', '')} / 若い女性の立場:{r.get('young', '')} / 若い女性の外見:{r.get('young_look', '')} / 主人公の外見:{r.get('hero_look', '')} / 前置き:{r.get('intro', '')}" for r in (recent or [])[:8])
    banned = sorted({w for r in (recent or [])[:6] for w in (r.get("object", ""), r.get("red", "")) if w}
                    | {"手紙", "はがき", "置き手紙", "日記", "ノート", "遺書"})   # 2026-11-14: 편지 이야기 그만
    used_forms = {r.get("intro_form") for r in (recent or [])[:10]}
    intro_form = random.choice([f for f in INTRO_FORMS if f not in used_forms] or INTRO_FORMS)
    era, era_things = random.choice(ERA_PAST)
    pw = pick_place_weather([r.get("region", "") for r in (recent or [])])
    hero = "女性"   # 시청자 65% 가 여성·55세 이상 89% (YouTube 분석, 2026-11) — 작가 결정: 주인공은 여성으로 고정
    user = (f"今回の題材の型（必須）: {kind or '自由'}" + (f" — {kdesc}" if kdesc else "") + "\n"
            f"前置き（narrator_intro）の型（必須）: {intro_form}\n"
            f"回想の時代（必須）: {era} — 例: {era_things}\n"
            + (viral + "\n" if viral else "") + seed_prompt(seed or {})
            + ("これまでの全作品（同じ商売・職業・店・小道具・出来事の組み合わせを繰り返さない。例: 閉店する豆腐屋が既にあれば、閉店する店の話は別の形にする）:\n"
               + archive + "\n" if archive else "")
            + ("この作品の組み立て（必須）:\n" + genre_build(kind) + "\n" if genre_build(kind) else "") +
            f"物語の舞台（必須）: {pw['region']}（{pw['region_en']}）。いま（2020年代）の季節は{pw['month']}月・{pw['season']}にする\n"
            f"表紙（cover_scene・cover_chapter）の天気と光（必須）: {pw['weather_en']}\n"
            f"主人公（視点人物）: 50〜60歳の{hero}（視聴者は50〜70代の女性が中心。その人が自分のこととして聴ける人物にする）\n\n"
            f"検索語リスト（日本・YouTube自動補完、実際に検索されている言葉）:\n" +
            "\n".join(f"- {q}" for q in queries) +
            f"\n\n章の数: ちょうど {n_chapters} 章\n"
            f"最近の作品（タイトル・小道具・赤いもの・舞台を重ねない）:\n{rec or 'なし'}\n"
            f"使用禁止の小道具・赤いもの: {', '.join(banned) or 'なし'}\n"
            f"ほかに作った作品: {', '.join(made_titles[:20]) or 'なし'}\nJSONのみ出力。")
    plan = _json_call(api_key, PLAN_SYSTEM, user, max_tokens=16000)
    chs = [c for c in (plan.get("chapters") or []) if isinstance(c, dict)][:n_chapters]
    if len(chs) < 3:
        raise ValueError("설계에 장이 부족합니다.")
    for i, c in enumerate(chs):
        c["no"] = i + 1
    plan["chapters"] = chs
    if kind:
        plan["kind"] = kind
    plan["intro_form"] = intro_form
    plan.update({k: pw[k] for k in ("region", "region_en", "month", "season", "weather", "weather_en")})
    plan["era"] = era
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
                    "region": pl.get("region", ""),
                    "young": (pl.get("young_woman") or {}).get("role", ""),
                    "young_look": (pl.get("young_woman") or {}).get("look_en", "")[:90],
                    "hero_look": (pl.get("heroine") or {}).get("look_en", "")[:90],
                    "intro": pl.get("narrator_intro", "")[:60], "intro_form": pl.get("intro_form", "")})
    return out


def story_archive(keys: dict, skip_pid: str = "", limit: int = 60) -> str:
    """지금까지 만든 편 전체(최대 60편)의 한 줄 요약 — 소재·가게·직업·소품이 겹치지 않게 설계와 편집 회의에 준다.
    (최근 8편만 보던 때, 사흘 전의 『土曜日の豆腐屋』를 모르고 '문 닫는 두부 가게'를 다시 고른 일이 있었다 — 2026-11-08)"""
    from concurrent.futures import ThreadPoolExecutor
    idx = cloud_index(keys)
    pids = [p for p in sorted(idx, reverse=True) if p != skip_pid][:limit]

    def one(pid):
        try:
            pl = cloud_state(keys, pid).get("plan") or {}
        except Exception:
            return ""
        if not pl.get("title_ja"):
            return ""
        st_ = pl.get("setting") or {}
        return (f"- 『{pl.get('title_ja', '')}』 型:{pl.get('kind', '?')} / 舞台:{st_.get('place', '')} / 小道具:{st_.get('object', '')} / "
                f"{(pl.get('logline_ja') or '')[:70]}")
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(one, pids) if r]
    return "\n".join(rows)


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
- 耳で一度で分かる数字の書き方:
  ・年は和暦が基本（昭和六十年、平成元年、平成七年）。西暦を使うなら位取りで書く（千九百八十九年）。「一九八九年」のような一字ずつの書き方はしない。
  ・時刻は「午後三時」「夜の九時すぎ」。日付は「三月十日」。
  ・読み方が二つある言葉はひらがなで書く（はたち、ついたち、ひとり、ふたり、ひとつ、ふたつ、きょう、あした、おととし）。
  ・電話番号・番地・金額の細かい数字は出さない（「駅前の古いアパートの二階」「千円札が三枚」程度にする）。
- 感情を説明しない。手・物・音・匂いで見せる。「モヤモヤした」「腹が立った」「悲しくなった」と書かない。泣く場面で人物を泣かせすぎない（人物が泣くと聴き手は泣かない）。
- 章の最後の一文は、次の章を聴きたくなる一文で終える（最終章は物語の最後の一行）。

[台詞の決まり]
- どの台詞も、欲しがる・守る・避ける・責める・誘う・押す のどれかをしている。説明のための台詞（「あなたも知っての通り」）は書かない。
- 言葉と本心をずらす。気持ちは別の話題・動作・沈黙で出す（「ご飯、食べた？」）。ただし聴き手が本心に気づく手がかりは必ず残す。
- 人物ごとに話し方を変える: 世代（六十代の主人公、七十代の義母、二十代の孫で語尾も語彙も違う。若い人に古い女性語「〜だわ」「〜かしら」を言わせない）、
  関係（敬語とタメ口。関係が変わる場面では言葉づかいも変わり、それ自体を転換点にする）。
- 舞台の土地の生まれの人物は、その土地の言葉を一言二言だけ混ぜる（聴いて分かる程度に）。
- 同じ感情を同じ言葉で三回以上言わせない。同じ言い回し・同じ動作を繰り返さない。
- 意味のない動作は書かない（「視線が止まる」「口を開きかけて閉じる」）。動作は物・情報・関係のどれかを変える。
- 一文は息つぎできる長さにし、読点は朗読の息の位置に置く。

[下の作家ルールは韓国語で書かれた原則です。日本語で書くときもこの原則をそのまま守ってください]
"""


EDIT_SYSTEM = """あなたは日本の朗読ドラマのベテラン編集者です（書いた作家とは別人。点数を甘くしない、迷ったら低い方）。
60〜70代の女性が夜に耳で聴く短編の原稿を、設計図と照らして読みます。
採点（各0〜10点）:
 agency（クライマックスを主人公が自分の行動で決めたか。偶然・第三者・見つめるだけ・気づくだけは3点以下）
 payoff（設計図の伏線がすべて回収されたか。植えていない答えで解決していないか）
 temperature（感情のいちばん高い場面の前後で温度差が大きいか）
 promise（題材の型の約束を果たしたか。スカッとなら胸がすき、感動なら泣ける、恋なら距離が動く）
 questions（各章の終わりに次を聴きたくなる問いがあるか）
 reality（お金・相続・年金・名義・離婚・病院などの手続きと金額が日本の現実と常識に合っているか）
 dialogue（台詞が自然な日本語か。世代・関係・土地で話し方が分かれているか。説明台詞・同じ言い回しの繰り返し・感情の説明がないか）
 opening（第1章の冒頭3文で出来事が始まるか）
直すべき章を最大3つ選び、具体的な直し方を書く（「もっと良く」ではなく「第5章で、相手が序盤に言った〇〇を主人公が自分で突きつける場面にする」のように）。
reality が6点以下なら、その問題がある章は必ず直す対象に入れる。
JSONだけを出力: {"overall": "全体の講評（日本語2〜3文）", "scores": {"agency": 0, "payoff": 0, "temperature": 0, "promise": 0, "questions": 0, "reality": 0, "dialogue": 0, "opening": 0},
 "fix": [{"no": 章番号, "note": "具体的な直し方"}]}"""


def edit_pass(api_key: str, plan: dict, chs: list) -> dict:
    """완성도 게이트: 원고 전체를 설계도와 대조해 8항목 채점 → 약한 장 최대 3개에 고칠 점."""
    full = "\n\n".join(f"第{c['no']}章「{c.get('title_ja', '')}」\n{c.get('text', '')}" for c in chs)
    design = {k: plan.get(k) for k in ("kind", "logline_ja", "turn", "core", "plants", "ally", "settlement", "ending_ja") if plan.get(k)}
    try:
        gb = genre_build(plan.get("kind", ""))
        rv = _json_call(api_key, EDIT_SYSTEM, f"作品: {plan.get('title_ja')}\n設計図: {json.dumps(design, ensure_ascii=False)}\n"
                        + (f"この型の組み立て（promise はこれを満たしたかで採点）:\n{gb}\n" if gb else "")
                        + (f"{dialect_rule(plan.get('region', ''))}→ 舞台と違う地方の方言が一言でも混ざっていたら dialogue を下げ、その章を fix に入れる。\n"
                           if dialect_rule(plan.get("region", "")) else "") + f"\n{full}", 2500)
        fix = [f for f in (rv.get("fix") or []) if isinstance(f, dict) and f.get("note")][:3]
        sc = rv.get("scores") if isinstance(rv.get("scores"), dict) else {}
        return {"overall": rv.get("overall", ""), "scores": sc, "fix": fix}
    except Exception as e:
        print(f"[rodoku] 편집 검토 실패 → 건너뜀: {e}", flush=True)
        return {"overall": "", "fix": [], "error": str(e)[:200]}


def _int0(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def write_chapter(api_key: str, plan: dict, ch: dict, prev_text: str, target_chars: int, note: str = "",
                  draft: str = "") -> str:
    system = WRITE_SYSTEM_HEAD + _novel_rules()
    design = {k: plan.get(k) for k in ("title_ja", "logline_ja", "setting", "region", "characters", "young_woman", "narrator_intro",
                                       "turn", "ending_ja", "core", "ally", "settlement") if plan.get(k)}
    outline = [{"no": c["no"], "title_ja": c.get("title_ja"), "beat": c.get("beat_ko"), "question": c.get("question", "")}
               for c in plan["chapters"]]
    pl = [p for p in (plan.get("plants") or []) if isinstance(p, dict)]
    here = ([f"この章で植える伏線: {p.get('what', '')}（目立たせすぎない）" for p in pl if _int0(p.get("plant_ch")) == ch["no"]]
            + [f"この章で回収する伏線: {p.get('what', '')} → {p.get('meaning', '')}" for p in pl if _int0(p.get("payoff_ch")) == ch["no"]])
    here += [f"この章に必ずそのまま入れる一文（60秒ショートで切り出すため、一字も変えない）: {x.get('line', '')}"
             for x in (plan.get("short_lines") or []) if isinstance(x, dict) and _int0(x.get("ch")) == ch["no"] and x.get("line")]
    pq = next((c.get("question", "") for c in plan["chapters"] if c.get("no") == ch["no"]), "")
    user = (f"[作品設計]\n{json.dumps(design, ensure_ascii=False)}\n\n[全章の流れ]\n{json.dumps(outline, ensure_ascii=False)}\n\n"
            f"[いま書く章] 第{ch['no']}章「{ch.get('title_ja', '')}」: {ch.get('beat_ko', '')}\n"
            + ("\n".join(here) + "\n" if here else "")
            + (f"この章の終わりに聴き手に残す問い: {pq}\n" if pq else "")
            + dialect_rule(plan.get("region", "")) +
            f"[分量] 空白を除いて {int(target_chars * 0.9)}〜{int(target_chars * 1.1)} 字\n\n"
            + (f"[直前の章の終わり]\n{prev_text[-600:]}\n\n" if prev_text else "")
            + (f"[編集者の指摘 — この点を直して書き直す]\n{note}\n\n[前回の原稿]\n{draft}\n\n" if note else "")
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


OUTRO_JA = "お聴きくださり、ありがとうございました。また、次のお話で。"   # 짧게 — 등록 안내는 화면 카드 글자로만
COLD_SYSTEM = """あなたは朗読ドラマの編集者です。本文から、動画の冒頭（タイトルの前）に置く一文を選びます。
条件: 本文の文をそのまま抜き出す（改変しない）。空白を除いて15〜45字。聴いた人が「なぜ？」と続きを知りたくなる文。
物語の結末・最後の答えは明かさない。JSONだけを出力: {"line": "抜き出した一文"}"""


def pick_cold_open(api_key: str, state: dict) -> str:
    """콜드 오픈 한 문장 — 반전 장 본문에서 그대로 뽑는다 (본문에 없는 문장이면 버린다)."""
    plan, chs = state["plan"], state["chapters"]
    try:
        tno = int(plan.get("turn_chapter") or 0)
    except (TypeError, ValueError):
        tno = 0
    c = next((x for x in chs if x["no"] == tno), chs[max(len(chs) - 2, 0)])
    text = c.get("text", "")
    try:
        line = (_json_call(api_key, COLD_SYSTEM, f"作品: {plan.get('title_ja')}\n\n[本文]\n{text}", 400).get("line") or "").strip()
    except Exception as e:
        print(f"[rodoku] 콜드 오픈 고르기 실패: {e}", flush=True)
        line = ""
    if line and re.sub(r"\s", "", line) in re.sub(r"\s", "", text) and 8 <= _n(line) <= 60:
        return line
    return ""


def _caption_pages(text: str, W: int = 1920) -> list:
    """자막 문장 → 2줄씩 나눈 페이지 목록 (한 문장이 2줄을 넘어도 잘리지 않게)."""
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SERIF_BOLD, phrase_wrap
    d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    lines = phrase_wrap(d, text, jp_font(JP_SERIF_BOLD, 60), W - 360)
    return [lines[i:i + 2] for i in range(0, len(lines), 2)] or [[]]


def _caption_png(out: str, text: str, W: int = 1920, H: int = 1080, lines: list = None) -> str:
    """콜드 오픈·앞말 자막 — 아래쪽에 낭독 문장 (lines 를 주면 그 줄만)."""
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SERIF_BOLD, phrase_wrap
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = jp_font(JP_SERIF_BOLD, 60)
    if lines is None:
        lines = phrase_wrap(d, text, f, W - 360)[:2]
    y0 = H - 120 - len(lines) * 84
    d.rectangle([0, y0 - 40, W, H], fill=(16, 12, 10, 120))
    for i, ln in enumerate(lines):
        d.text((W // 2, y0 + i * 84), ln, font=f, fill=(255, 244, 234, 255), anchor="ma",
               stroke_width=3, stroke_fill=(20, 14, 12, 255))
    img.save(out, "PNG")
    return out


def _caption_clip(loop: str, text: str, sec: float, lead: float, speech: float, out: str) -> str:
    """장면 루프 + 낭독 자막. 문장이 길면 2줄씩 여러 장으로 나눠, 낭독 길이에 맞춰 차례로 바꿔 보여 준다."""
    pages = _caption_pages(text)
    if len(pages) <= 1:
        return _outro_clip(loop, _caption_png(out.replace(".mp4", ".png"), text), sec, out)
    sizes = [max(1, sum(len(l) for l in pg)) for pg in pages]
    total = float(sum(sizes))
    pngs, cuts, t = [], [], lead
    for k, pg in enumerate(pages):
        pngs.append(_caption_png(out.replace(".mp4", f"_{k}.png"), "", lines=pg))
        t1 = sec if k == len(pages) - 1 else t + speech * sizes[k] / total
        cuts.append((0.0 if k == 0 else t, t1))
        t = t1
    ins = ["-stream_loop", "-1", "-i", loop]
    for fp in pngs:
        ins += ["-loop", "1", "-framerate", str(hz.FPS), "-t", f"{sec}", "-i", fp]
    fc, last = "[0:v]setpts=PTS-STARTPTS[b0];", "b0"
    for k, (a, b) in enumerate(cuts):
        fade = ",fade=t=in:st=0:d=0.8:alpha=1" if k == 0 else ""
        fc += f"[{k + 1}:v]format=rgba{fade}[o{k}];[{last}][o{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[b{k + 1}];"
        last = f"b{k + 1}"
    fc += f"[{last}]format=yuv420p[v]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", fc, "-map", "[v]", *X264_FAST,
                    "-crf", "20", "-an", "-t", f"{sec}", out], check=True, timeout=600)
    return out


OUTRO_CARD = ("ご視聴ありがとうございました", "チャンネル登録で、次のお話が届きます")


ENDSCREEN_SEC = 20.0


def _endcard_png(out: str, W: int = 1920, H: int = 1080) -> str:
    """마무리 카드 — 글자는 위쪽에만, 가운데·아래는 YouTube 종료 화면 요소(다음 영상 · 구독)가 놓일 자리로 비워 둔다."""
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SERIF_BOLD
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(16, 12, 10, 110))
    d.text((W // 2, 120), OUTRO_CARD[0], font=jp_font(JP_SERIF_BOLD, 72), fill=(255, 244, 234, 255), anchor="ma",
           stroke_width=3, stroke_fill=(20, 14, 12, 255))
    d.text((W // 2, 230), OUTRO_CARD[1], font=jp_font(JP_SERIF_BOLD, 40), fill=(227, 181, 164, 255), anchor="ma")
    d.text((W // 2, H - 110), "次のお話も、どうぞ", font=jp_font(JP_SERIF_BOLD, 44), fill=(255, 244, 234, 255), anchor="ma",
           stroke_width=3, stroke_fill=(20, 14, 12, 255))
    img.save(out, "PNG")
    return out


def _outro_clip(loop: str, png: str, sec: float, out: str) -> str:
    """마지막 장 루프를 sec 초 반복 + 마무리 카드 (본편과 같은 인코딩 규격)."""
    fc = ("[0:v]setpts=PTS-STARTPTS[b];[1:v]format=rgba,fade=t=in:st=0:d=0.8:alpha=1[o];"
          "[b][o]overlay=0:0,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", loop, "-loop", "1", "-framerate",
                    str(hz.FPS), "-t", f"{sec}", "-i", png, "-filter_complex", fc, "-map", "[v]", *X264_FAST,
                    "-crf", "20", "-an", "-t", f"{sec}", out], check=True, timeout=600)
    return out


def _card_clip(loop: str, png: str, sec: float, out: str) -> str:
    """루프 영상의 끝 부분(sec 초) + 카드 글자 → 같은 인코딩 규격의 짧은 클립.
    루프 끝에서 잘라 오므로, 뒤에 붙는 본문(루프 처음부터)과 화면이 끊김 없이 이어진다."""
    ld = hz.duration(loop) or float(hz.KB_PERIOD)
    a = max(ld - sec, 0.0)
    fc = (f"[0:v]trim={a:.3f}:{a + sec:.3f},setpts=PTS-STARTPTS[b];[1:v]format=rgba,fade=t=in:st=0:d=0.6:alpha=1,"
          f"fade=t=out:st={sec - 0.6:.2f}:d=0.6:alpha=1[o];[b][o]overlay=0:0,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", loop, "-loop", "1", "-framerate", str(hz.FPS),
                    "-t", f"{sec}", "-i", png, "-filter_complex", fc, "-map", "[v]", *X264_FAST, "-crf", "20",
                    "-an", "-t", f"{sec}", out], check=True, timeout=600)
    return out


SUBS_ON = True   # 본문 자막을 화면에 입힌다 (2026-11: 경쟁 채널 분석 — 소리 끄고 보는 시청자·고령 시청자)


def _chapter_subs(keys: dict, c: dict, head: str) -> list:
    """장 낭독 → 자막 줄 [(글자, 시작, 끝)] (장 시작 기준 초). 한 번 맞추면 c['subs'] 에 저장해 다시 쓰지 않는다."""
    stamp = (c.get("audio") or {}).get("seconds")
    if c.get("subs") is not None and c.get("subs_for") == stamp:
        return c["subs"]
    cues = _cues(_align(keys, c["audio"]["local"], speakable(head + c.get("text", ""))))
    if cues and cues[0][0].startswith("第"):     # 「第一章、…。」 은 제목 카드가 보여 주므로 자막에서 뺀다
        cues = cues[1:]
    c["subs"] = [[t, round(a, 3), round(b, 3)] for t, a, b in cues]
    c["subs_for"] = stamp
    return c["subs"]


def _burn_subs(state, keys, job, video: str, spans: list, total: float, save_fn=None) -> str:
    """완성 화면(video)에 본문 자막을 한 번에 입힌다. spans = [(장 시작 시각, 장)]. 실패하면 원래 화면을 돌려준다."""
    from src.assembler import _caption_track
    from src.scenestory import jp_font, JP_SERIF_BOLD, phrase_wrap
    from PIL import Image, ImageDraw
    try:
        rows = []
        for t0, c in spans:
            head = f"第{_kanji_num(c['no'])}章、{c['title_ja']}。\n\n"
            for txt, a, b in _chapter_subs(keys, c, head):
                rows.append([t0 + a, t0 + max(b, a + 0.8), txt])
        if save_fn:
            hz._save(save_fn, state)   # 맞춘 자막 타이밍 저장 (다시 합성할 때 API 를 또 부르지 않게)
        if not rows:
            return video
        rows.sort(key=lambda r: r[0])
        for i in range(len(rows) - 1):          # 다음 자막과 겹치지 않게
            rows[i][1] = min(rows[i][1] + 0.3, rows[i + 1][0] - 0.05)
        d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        f = jp_font(JP_SERIF_BOLD, 60)
        caps = []
        for i, (a, b, txt) in enumerate(rows):
            lines = phrase_wrap(d, txt, f, 1920 - 360)[:2]
            caps.append((a, b, _caption_png(pf(state, "work", "subs", f"s{i:04d}.png"), "", lines=lines)))
        lst = _caption_track(caps, total, pf(state, "work", "subs", "track.mp4"))
        out = pf(state, "work", "video_subs.mp4")
        hz._run_ffmpeg(["-threads", "1", "-i", video, "-f", "concat", "-safe", "0", "-i", lst, "-filter_complex",
                        "[1:v]format=rgba[c];[0:v][c]overlay=0:0:eof_action=pass,format=yuv420p[v]", "-map", "[v]",
                        # 30~40분 전체를 다시 인코딩하는 단계라 CPU 를 가장 많이 쓴다 → ultrafast (Streamlit CPU 제한 회피, 약 3배 가볍다)
                        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "animation", "-crf", "24", "-pix_fmt", "yuv420p",
                        # 1코어만 쓰게 해 Streamlit 2코어 상한에 붙지 않도록 (시간은 조금 더 걸리지만 CPU 제한 경고·화면 멈춤을 막는다)
                        "-bf", "0", "-threads", "1", "-filter_complex_threads", "1", "-an", "-t", f"{total:.2f}", out],
                       total, job, "[8/10] 합성 · 자막 입히기", nice=True)
        state["subs_burned"] = len(caps)
        return out
    except Exception as e:
        state["subs_error"] = f"{type(e).__name__}: {e}"[:300]
        print(f"[rodoku] 자막 입히기 실패 → 자막 없이: {e}", flush=True)
        return video


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
選ぶ基準（よく見られたショートの共通点）: 人生が決まる瞬間の一節を選ぶ。離婚届を出す前の夜、閉店の最後の日、
壁越し・電話越しに本音を聞いてしまった瞬間、通帳や契約書の名義が明かされる瞬間など。最初の一文で「いつ・誰が・何が起きているか」が伝わる箇所から始める。
【最初の一文が勝負】ショートは最初の1秒で指が止まるかで決まる（2026-11-11: 見ずにスワイプ57%）。抜き出しの最初の一文は、その一節でいちばん強い一言にする。
できれば人物の台詞「」（見下す言葉、隠していた本音、取り返しのつかない宣告、金額や年数の入った一言）。挨拶・説明・天気・丁寧な前置きから始めない。
hook_line は、最初の一文が台詞ならその台詞を「」付きで14字以内に縮めたもの。台詞でなければ8〜14字の問いかけ。
hook_line はそれだけ読んで意味が一つに決まる言葉にする（2026-11-14『A-17の里芋』の「里芋って地味じゃない」は見下しか褒め言葉か読めない）。見下す台詞なら語尾の棘を残す（〜じゃない？／〜でしょ／〜のくせに）。
【最後の一文も勝負】抜き出しは「次に何が起きるか」が宙づりになる文で終える: 答えの出ていない問い、明かされる直前の物・名前・金額、取り返しのつかない宣告。
動作の描写（手を伸ばした／立ち上がった／そこに立っていた）や情景で終えない（2026-11-14『A-17の里芋』は「里芋に手を伸ばした。」で終わり、続きが気にならなかった）。
end_tease は、最後に画面に2秒出す問い（12〜20字、日本語、「」なし、？で終える）。抜き出しの続きで視聴者がいちばん知りたいことを問う。結末は明かさない（例: その区画の名義は、誰のものだったのか？）。
face_en は、その最初の一文を聞いた瞬間の主人公（50代の女性）の顔を英語で一文。表情は一つだけ断定して書く（例: her eyes wide and lips slightly parted in stunned silence / her jaw set and eyes cold with quiet resolve）。
JSONだけを出力: {"chapter": 章番号, "excerpt": "抜き出した本文", "hook_line": "画面上部に出す文言", "face_en": "English", "end_tease": "最後に出す問い", "shorts_title": "ショートのタイトル（30字以内）。物語の中の具体的な数字を一つ必ず入れる（年数・年齢・時刻・金額・回数。例：38年後、26年目、毎朝4時、2万円、67歳）＋誰の話か＋謎の物か言葉。算用数字で書く。例：『38年後の再会に節子が取り出したもの』『毎朝4時に消える夫、ポケットの鍵』。『〜年ぶり』『〜年越し』は本当に年月の隔たりが物語の核のときだけ。#朗読 と題材に合うハッシュタグ1個を含む"}"""


def _vertical_anime(raw: str, out: str, sec: int = 12) -> str:
    """움직임 클립 → 초당 7.5장 앞뒤 루프 → 9:16 가운데 자르기 → sec 초 길이."""
    one = out.replace(".mp4", "_one.mp4")
    n = max(int(hz.duration(raw) * ANIME_FPS), 4)
    vf = (f"[0:v]fps={ANIME_FPS},split[f][b];[b]reverse,trim=start_frame=1:end_frame={n - 1},setpts=PTS-STARTPTS[r];"
          f"[f][r]concat=n=2:v=1:a=0,fps={hz.FPS},scale=-2:1920,crop=1080:1920,setsar=1,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-filter_complex", vf, "-map", "[v]",
                    *X264_FAST, "-crf", "21", "-an", one], check=True, timeout=600)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", one, "-t", f"{sec}",
                    "-c", "copy", out], check=True, timeout=300)
    return out


def _vertical_loop(image: str, out: str, sec: int = 12) -> str:
    n = int(sec * hz.FPS)
    vf = (f"scale=-2:2400,crop=1350:2400,zoompan=z='1+0.015*(1-cos(2*PI*on/{n}))':"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps={hz.FPS},setsar=1,format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(hz.FPS), "-t", f"{sec}",
                    "-i", image, "-vf", vf, "-frames:v", str(n), *X264_FAST, "-crf", "21", "-an", out],
                   check=True, timeout=600)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ⑧ 업로드 정보
# ─────────────────────────────────────────────────────────────────────────────
PACK_SYSTEM = """あなたはYouTubeチャンネル「SceneStory」（50〜70代の女性向けオリジナル朗読ドラマ）のアップロード担当です。JSONだけを出力:
{"title": "本文だけ（前後の【】はあとで付ける）。60〜85字。人気のシニア朗読チャンネルの型で組む（2026-11-12 調査: 再生上位の題はすべてこの形）:
           ①具体的な時と状況を数字で（離婚2日後の早朝6時／定年退職の翌朝／結婚30年目の誕生日）→ ②相手の台詞を話者付きで（義母「…」夫「…」息子の嫁「…」。見下す・欲深い・突き放す言葉）→
           ③主人公の静かな返し 私「…」→ ④「直後、」「3日後、」「→結果」など、形勢が変わる予告で「…」と終える。時刻・金額・年数は算用数字。
           例：定年退職の翌朝、夫「これからは俺の年金で食わせてやる」私「では、私の通帳はお返ししますね」3日後、夫の顔が真っ青に…
           例：父の葬儀の翌日、兄「家も土地も長男の俺が継ぐ」兄嫁「あなたは他人でしょ」私「ええ、では遺言書を読みますね」直後…
           スカッと以外の型（感動・恋・懐かしい）も同じ形で、②を相手の忘れられない一言、④を「その理由に…」「40年後に届いた答えは…」にする。
           予告ショートの台詞が渡されたときは、それを②の最初の台詞として一字も変えずに使う（ショートを見た人が同じ話だと気づくため）。
           並びは毎回同じにしない（同じ型の題が並ぶと量産チャンネルに見え、YouTube の収益審査で不利）。ユーザー文の「並び」に従う:
           A=①状況→②台詞→③返し→④予告 / B=②台詞から始め→①状況→④予告（③は省いてよい）/ C=数字の事実から始める（「30年分の通帳を…」「年金月6万の母に…」）→②台詞→④予告。
           作品タイトルは入れない。結末・真実は書かない",
 "thumb_quote": "サムネイルに特大で入れる相手の台詞（「」付き、16字以内、②の台詞を縮めたもの）",
 "title_order": "使った並び（A/B/C）",
 "thumb_sub": "サムネイル上部の小さな一行（12字以内、①の数字入りの状況。例：離婚2日後の朝6時）",
 "thumb_reply": "予備サムネイル用、主人公の静かな返しの台詞（「」付き、14字以内、③を縮めたもの）",
 "description": "1行目は物語の最初の場面を一文で（例：午前4時。となりの布団は、もう空っぽだった。）。2〜3行目で謎と疑いを重ねる（算用数字可）。結末は書かない。
                 最後に、作家オリジナル作品であること、寝る前やお茶の時間にどうぞ、の一言。全体5〜7行",
 "tags": ["検索語・ジャンル語 12〜15個"],
 "hashtags": ["#朗読", "#朗読ドラマ", 題材に合う1個],
 "cover_text": "サムネイルに大きく入れる一行（14字以内）。物語の結果や核心を数字ひとつで見せる（例：残高、三千百八十七円。／四十年分の、領収書）。結末そのものは書かない",
 "pinned_comment": "本編に固定するコメント。2〜3行。物語の小道具や場面に触れ、視聴者が自分の思い出を書きたくなる問いかけで終える（例：あなたにも、ずっと渡せずにいる物はありますか。）。押しつけがましい登録のお願いは書かない",
 "shorts_comment": "予告ショートに固定するコメント。1〜2行。問いかけ＋『本編は画面下のリンク（チャンネル名の下）からどうぞ』"}
性的な言葉は使わない。相手の嘲笑の台詞に限り、末尾の「w」は使ってよい（ジャンルの慣習）。主人公は品よく。"""

UPLOAD_SETTINGS = [
    ("카테고리", "エンターテイメント (엔터테인먼트)"),
    ("아동용 여부", "아니요, 아동용이 아닙니다"),
    ("동영상 언어", "일본어"),
    ("변경되거나 합성된 콘텐츠", "AI 음성·AI 그림이 들어가므로 '예'"),
    ("올리는 순서", "매일 본편 1편 + 예고 쇼츠 1개 (본편 먼저 → 쇼츠는 같은 날, 쇼츠 고정 댓글로 본편 안내)"),
    ("예고 쇼츠", "올린 뒤 스튜디오(컴퓨터) → 콘텐츠 → 쇼츠 → 관련 동영상에 본편 선택 · 고정 댓글 고정"),
    ("종료 화면", "YouTube 스튜디오(PC) → 동영상 → 종료 화면: 마지막 20초가 비어 있으니 '동영상(최신 업로드)'과 '구독' 두 개를 화면 가운데에 놓기"),
    ("고정 댓글", "본편·쇼츠 모두 위 '고정 댓글'을 직접 달고 고정 (질문형 → 시청자 댓글 유도)"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 전체 작업
# ─────────────────────────────────────────────────────────────────────────────
# ── 그림체: 단순하고 따뜻한 손그림 인물 + 빛나는 정밀 배경(하늘·구름·빛·반사) + 장마다 단 하나의 주홍색 (채널 표식) ──
ART_PREFIX = (
    "Contemporary Japanese animated feature film still, refined modern adult character design in a mature josei style: "
    "every adult looks their real age, realistic adult proportions, delicate fine linework, calm natural eyes "
    "(not oversized, no blush stickers), natural small nose and lips, soft "
    "gradient cel shading on skin, individually rendered hair strands with glossy light sheen. Hyper-detailed "
    "luminous painted background with glowing light, golden highlights, soft lens flare and tiny drifting light "
    "particles, lived-in everyday Japanese details true to the era named in the scene, wide cinematic 16:9 composition."
)
ART_SUFFIX = (
    " The vermilion red object is the only red in the whole image. "
    "The woman in her fifties may show her face; people aged seventy or older are seen from behind, in silhouette or small in the distance, with no facial features. "
    "Hands are relaxed and simple — resting in the lap, at the sides, in pockets or out of frame; no raised hands, no gestures. "
    "No text, no letters, no numbers, no signboard writing, no road signs with symbols."
)

# 중간 영상: veryfast 그대로 (superfast·ultrafast 는 CPU 는 20~40% 줄지만 파일이 3배 커져 완성본이 무거워진다 — 2026-11-08 실측)
X264_FAST = list(hz.X264)

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
        if (idx.get(pid) or {}).get("purged"):
            row["purged"] = idx[pid]["purged"]
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


def purge_cloud(keys: dict, pid: str) -> int:
    """'영구 삭제': R2 의 영상·음성·그림을 지우고 되살리기 목록에서 뺀다.
    state.json(작은 설계 기록)만 남겨, 다음 편이 같은 이야기·지역·소품을 되풀이하지 않게 한다."""
    from src import r2_store
    n = r2_store.delete_prefix(keys, f"scenestory/{pid}/", keep=("state.json",))
    idx = r2_store.get_json(keys, CLOUD_INDEX) or {}
    if pid in idx:
        idx[pid]["purged"] = time.strftime("%Y-%m-%d %H:%M")
        r2_store.put_json(keys, CLOUD_INDEX, idx)
    return n


def _rss_mb() -> int:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


# ── 서버 재시작 뒤 자동으로 이어 만들기 ──
AUTO_RESUME_MAX = 3            # 같은 편을 자동으로 다시 시작하는 최대 횟수 (매번 같은 오류로 비용만 쓰는 것 방지)
AUTO_RESUME_HOURS = 12         # 마지막 저장 후 이 시간이 지난 편은 건드리지 않는다
_AUTO_DONE = {"checked": False}


def auto_resume(manager, keys: dict) -> list:
    """앱이 (재)시작된 뒤 처음 열릴 때 한 번: 멈춘 채 남은 朗読ドラマ 편을 찾아 이어서 만든다.
    서버 목록에 없으면 R2 의 상태로 되살린다. 작가가 직접 멈춘 편·완성된 편·오래된 편은 건너뛴다."""
    if _AUTO_DONE["checked"]:
        return []
    _AUTO_DONE["checked"] = True
    started = []
    try:
        local = {}
        for p in manager.list_projects():
            if p.get("channel") == "scenestory":
                try:
                    st_ = manager.load_state(p["dir"])
                    local[st_["project_id"]] = st_
                except Exception:
                    pass
        cands = dict(local)
        for pid, row in cloud_index(keys).items():
            if pid not in cands and row.get("stage") not in ("done", ""):
                try:
                    cands[pid] = cloud_state(keys, pid)
                except Exception:
                    pass
        now = time.time()
        newest = max((k for k, v in cands.items() if v.get("mode") == "rodoku"), default="")
        for pid, st_ in sorted(cands.items()):
            if pid != newest:            # 작가가 새 편으로 넘어갔으면 예전 미완성 편은 자동으로 되살리지 않는다
                continue
            if st_.get("mode") != "rodoku" or st_.get("stage") in ("done", "abandoned", None, "") or st_.get("user_stopped"):
                continue
            if hz.is_running(pid) or int(st_.get("auto_resumed", 0)) >= AUTO_RESUME_MAX:
                continue
            ts = st_.get("saved_at") or 0
            if ts and now - ts > AUTO_RESUME_HOURS * 3600:
                continue
            st_["auto_resumed"] = int(st_.get("auto_resumed", 0)) + 1
            manager.save_state(st_)
            made = [s.get("title", "") for k, s in local.items() if k != pid]
            if start_auto(st_, keys, manager.save_state, made):
                started.append(pid)
                print(f"[rodoku] 서버 재시작 뒤 자동으로 이어 만들기: {pid} ({st_.get('stage')}, {st_['auto_resumed']}번째)", flush=True)
    except Exception as e:
        print(f"[rodoku] 자동 이어 만들기 확인 실패: {e}", flush=True)
    return started


def start_auto(state: dict, keys: dict, save_fn, made_titles: list) -> bool:
    state.pop("user_stopped", None)            # 다시 시작하면 '멈춤' 표시는 지운다
    def save_both(s):
        s["saved_at"] = time.time()
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
        state["user_stopped"] = True            # 작가가 멈춘 편은 자동으로 다시 시작하지 않는다
        hz._save(save_fn, state)
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
        kind = pick_kind([r.get("kind", "") for r in recent], group=state.get("group", ""))
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
        if "viral" not in state and keys.get("YOUTUBE_API_KEY"):
            try:
                from src import viral as V
                _stage(job, state, save_fn, "plan", 1, "지금 터진 시니어 낭독 영상을 찾는 중")
                state["viral"] = V.find(keys["YOUTUBE_API_KEY"])
            except Exception as e:
                state["viral"] = []
                state["viral_error"] = f"{type(e).__name__}: {e}"[:300]
                print(f"[rodoku] 터진 영상 찾기 실패 → 없이 진행: {e}", flush=True)
            hz._save(save_fn, state)
        from src import viral as V
        kind_now = (state.get("trend") or {}).get("kind", "")
        if "_archive" not in state:
            try:
                state["_archive"] = story_archive(keys, state.get("project_id", ""))
            except Exception as e:
                state["_archive"] = ""
                print(f"[rodoku] 지난 편 목록 읽기 실패 → 최근 8편만: {e}", flush=True)
        if "seed" not in state:
            _stage(job, state, save_fn, "plan", 1, "편집 회의: 소재 후보 3개를 만들고 채점하는 중")
            try:
                rtxt = state.get("_archive") or "\n".join(f"- 『{r.get('title', '')}』 型:{r.get('kind', '?')} / 舞台:{r.get('place', '')}" for r in (recent or [])[:8])
                state["seed"] = pick_seed(ak, kind_now, next((d for k, d, _ in STORY_KINDS if k == kind_now), ""),
                                          state["trend"]["queries"], V.as_prompt(state.get("viral") or []), rtxt)
            except Exception as e:
                state["seed"] = {}
                state["seed_error"] = f"{type(e).__name__}: {e}"[:300]
                print(f"[rodoku] 소재 후보 채점 실패 → 예전 방식으로 설계: {e}", flush=True)
            hz._save(save_fn, state)
        _stage(job, state, save_fn, "plan", 1, "설계 중 (6장 골격·복선표·장별 질문)")
        plan = make_plan(ak, state["trend"]["queries"], n_ch, made_titles,
                         kind=kind_now, recent=recent,
                         viral=V.as_prompt(state.get("viral") or []), seed=state.get("seed") or {},
                         archive=state.get("_archive", ""))
        state["plan"] = plan
        state["title"] = f"{plan.get('title_ja', '')} ({plan.get('title_ko', '')})"
        state["topic"] = f"{plan.get('title_ja', '')} · {plan.get('title_ko', '')}"
        state["chapters"] = [{"no": c["no"], "title_ja": c.get("title_ja", ""), "beat_ko": c.get("beat_ko", ""),
                              "image_prompt": c.get("image_prompt", ""),
                              "motion_prompt": c.get("motion_prompt", ""), "ambience_en": c.get("ambience_en", ""),
                              "with_young": bool(c.get("with_young")) or (c["no"] == _cover_no(plan) and not plan.get("heroine")),
                              "with_hero": bool(c.get("with_hero")) or (c["no"] == _cover_no(plan) and bool(plan.get("heroine"))),
                              "extra": [{"image_prompt": m.get("image_prompt", ""), "motion_prompt": m.get("motion_prompt", ""),
                                         "with_young": bool(m.get("with_young")), "with_hero": bool(m.get("with_hero"))}
                                        for m in (c.get("more_scenes") or []) if isinstance(m, dict) and m.get("image_prompt")
                                        ][:max(int(state.get("n_scenes", DEFAULT_SCENES)) - 1, 0)]}
                             for c in plan["chapters"]]
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
    # ③-2 편집자 검토 → 약한 장 최대 2개 다시 쓰기
    if "edit" not in state:
        _stage(job, state, save_fn, "write", 2, "편집자 검토 중 (원고 전체)")
        ed = edit_pass(ak, plan, chs)
        for f in ed.get("fix", []):
            c = next((x for x in chs if x["no"] == int(f.get("no") or 0)), None)
            if not c:
                continue
            _stage(job, state, save_fn, "write", 2, f"제{c['no']}장 다시 쓰는 중 (편집자 지적 반영)")
            prev_c = next((x for x in chs if x["no"] == c["no"] - 1), None)
            try:
                c["text"] = write_chapter(ak, plan, c, (prev_c or {}).get("text", ""), per, note=f["note"], draft=c["text"])
                c["chars"] = _n(c["text"])
                f["done"] = True
            except Exception as e:
                f["error"] = str(e)[:200]
        state["edit"] = ed
        hz._save(save_fn, state)
    state["manuscript_chars"] = sum(c.get("chars", 0) for c in chs)

    # ④ 그림 — 장마다 장면 1~3장 (3장씩 동시에 그림)
    jobs = []
    for c in chs:
        for k, sc in enumerate([c] + list(c.get("extra") or [])):
            img = sc.setdefault("image", {})
            name = f"ch{c['no']:02d}.jpg" if k == 0 else f"ch{c['no']:02d}_s{k + 1}.jpg"
            if not hz.ensure_local(keys, img, pf(state, name)):
                jobs.append((c, k, sc, name))
    if jobs:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        done = 0
        _stage(job, state, save_fn, "images", 3, f"그림 {len(jobs)}장 (3장씩 동시에)")
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(_draw_scene, state, keys, ak, plan, c, k, sc, name): (c, k) for c, k, sc, name in jobs}
            for f in as_completed(futs):
                c, k = futs[f]
                done += 1
                try:
                    f.result()
                except Exception as e:
                    if k == 0:
                        raise
                    print(f"[rodoku] 제{c['no']}장 장면{k + 1} 그림 실패 → 장면 생략: {e}", flush=True)
                _stage(job, state, save_fn, "images", 3, f"그림 {done}/{len(jobs)} · 제{c['no']}장 장면{k + 1}")

    # ④-2 움직임 — 장마다 6초 움직임 클립 (실패한 장은 Ken Burns 로 대신)
    _make_motion(job, state, keys, save_fn)

    # ④-3 콜드 오픈 문장 (영상 첫머리, 제목 전에 반전 장의 한 문장)
    if "cold" not in state:
        _stage(job, state, save_fn, "voice", 5, "첫머리 한 문장 고르는 중")
        state["cold"] = {"text": pick_cold_open(ak, state)}
        hz._save(save_fn, state)

    # ⑤ 목소리
    from src.audio import generate_narration
    voice = keys.get("ELEVENLABS_VOICE_ID_JA") or JA_VOICE_ID
    cast = state.setdefault("cast_voices", {k: v for k, v in load_voices(keys).items() if v})
    kanji = "一二三四五六七八九十"
    for c in chs:
        au = c.setdefault("audio", {})
        if not hz.ensure_local(keys, au, pf(state, f"ch{c['no']:02d}.mp3")):
            _stage(job, state, save_fn, "voice", 5, f"제{c['no']}장 낭독")
            dest = pf(state, f"ch{c['no']:02d}.mp3")
            head = f"第{_kanji_num(c['no'])}章、{c['title_ja']}。\n\n"
            info = {}
            if cast:   # 배역 목소리: 지문은 낭독자, 「」 대사는 인물 목소리
                _stage(job, state, save_fn, "voice", 5, f"제{c['no']}장 낭독 (배역 목소리)")
                cast_narration(keys, ak, state, c, head, dest, voice, cast)
                info["model"] = "cast"
            else:
                generate_narration(keys.get("ELEVENLABS_API_KEY", ""), speakable(head + c["text"]), dest, voice_id=voice, info=info)
            au.update(local=dest, seconds=round(hz.duration(dest), 2), model=info.get("model", ""),
                      r2_key=keep(keys, state, dest, f"ch{c['no']:02d}.mp3", "audio/mpeg"))
            hz._save(save_fn, state)

    # ⑤-00 화자의 앞말 (30대 목소리가 옛이야기를 하는 이유 — 편마다 다르게)
    intro = state.setdefault("intro", {"text": (plan.get("narrator_intro") or "").strip()})
    if intro.get("text") and not hz.ensure_local(keys, intro, pf(state, "intro.mp3")) and not intro.get("error"):
        _stage(job, state, save_fn, "voice", 5, "화자의 앞말 낭독")
        try:
            dest = pf(state, "intro.mp3")
            generate_narration(keys.get("ELEVENLABS_API_KEY", ""), speakable(intro["text"]), dest, voice_id=voice, info={})
            intro.update(local=dest, seconds=round(hz.duration(dest), 2), r2_key=keep(keys, state, dest, "intro.mp3", "audio/mpeg"))
        except Exception as e:
            intro["error"] = f"{type(e).__name__}: {e}"[:200]
            print(f"[rodoku] 앞말 낭독 실패 → 생략: {e}", flush=True)
        hz._save(save_fn, state)

    # ⑤-0 콜드 오픈 낭독
    cold = state.get("cold") or {}
    if cold.get("text") and not hz.ensure_local(keys, cold, pf(state, "cold.mp3")) and not cold.get("error"):
        _stage(job, state, save_fn, "voice", 5, "첫머리 한 문장 낭독")
        try:
            dest = pf(state, "cold.mp3")
            generate_narration(keys.get("ELEVENLABS_API_KEY", ""), speakable(cold["text"]), dest, voice_id=voice, info={})
            cold.update(local=dest, seconds=round(hz.duration(dest), 2), r2_key=keep(keys, state, dest, "cold.mp3", "audio/mpeg"))
        except Exception as e:
            cold["error"] = f"{type(e).__name__}: {e}"[:200]
            print(f"[rodoku] 콜드 오픈 낭독 실패 → 생략: {e}", flush=True)
        hz._save(save_fn, state)

    # ⑤-1 마무리 인사 (구독·댓글 안내) — 실패해도 본편은 만든다
    ou = state.setdefault("outro", {})
    if not hz.ensure_local(keys, ou, pf(state, "outro.mp3")) and not ou.get("error"):
        _stage(job, state, save_fn, "voice", 5, "마무리 인사")
        try:
            dest = pf(state, "outro.mp3")
            generate_narration(keys.get("ELEVENLABS_API_KEY", ""), OUTRO_JA, dest, voice_id=voice, info={})
            ou.update(local=dest, seconds=round(hz.duration(dest), 2), r2_key=keep(keys, state, dest, "outro.mp3", "audio/mpeg"))
        except Exception as e:
            ou["error"] = f"{type(e).__name__}: {e}"[:200]
            print(f"[rodoku] 마무리 인사 실패 → 생략: {e}", flush=True)
        hz._save(save_fn, state)

    # ⑤-2 배경음악 — 편마다 이야기에 맞춰 새로 2곡 (반전 전 / 반전 후)
    _make_music(job, state, keys, save_fn)
    # ⑤-3 환경음 — 장마다 빗소리·건널목·매미 등
    if state.get("ambience_on", True):
        _make_ambience(job, state, keys, save_fn)

    # ⑥ 합성
    if not hz.usable((state.get("final") or {}).get("local", "")) and not (state.get("final") or {}).get("r2_key"):
        _stage(job, state, save_fn, "render", 7, "화면 루프 만드는 중")
        _render(job, state, keys, save_fn)

    # ⑦ 예고 쇼츠 3개 (장면을 바꿔서) + 각각 표지
    n_shorts = max(1, min(int(state.get("n_shorts", DEFAULT_SHORTS)), N_SHORTS))
    for slot in range(n_shorts):
        folder = "trailer" if slot == 0 else f"trailer{slot + 1}"
        get = (lambda: state.get("trailer") or {}) if slot == 0 else \
              (lambda: ((state.get("trailers") or []) + [{}, {}, {}])[slot - 1] or {})
        if not hz.usable(get().get("local", "")) and not get().get("r2_key"):
            _stage(job, state, save_fn, "trailer", 8, f"예고 쇼츠 {slot + 1}/{n_shorts} 만드는 중")
            try:
                _trailer(job, state, keys, slot)
            except Exception as e:
                err = {"error": f"{type(e).__name__}: {e}"[:300]}
                if slot == 0:
                    state["trailer"] = err
                else:
                    lst = state.setdefault("trailers", [])
                    while len(lst) < slot:
                        lst.append({})
                    lst[slot - 1] = err
                print(f"[rodoku] 예고 쇼츠 {slot + 1} 실패: {e}", flush=True)
            hz._save(save_fn, state)
        trl = get()
        if trl.get("local") and not hz.ensure_local(keys, trl.get("cover") or {}, pf(state, folder, "cover_1080x1920.jpg")):
            _stage(job, state, save_fn, "trailer", 8, f"예고 쇼츠 {slot + 1} 표지 그리는 중")
            try:
                _shorts_cover(state, keys, slot)
            except Exception as e:
                trl["cover"] = {"error": f"{type(e).__name__}: {e}"[:300]}
                print(f"[rodoku] 쇼츠 표지 {slot + 1} 실패: {e}", flush=True)
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


GPT_IMAGE_MODEL = "gpt-image-2"
GPT_SIZES = {"16:9": "1536x864", "9:16": "864x1536"}   # 가로·세로 모두 16의 배수 (gpt-image-2 크기 규칙)


# GPT Image 는 'realistic·hyper-detailed·lens flare' 같은 말을 사진·3D 로 받아들인다 → 2D 아니메로 못 박는다
GPT_STYLE_HEAD = ("2D hand-drawn Japanese anime illustration, a still frame from a contemporary theatrical anime film: "
                  "clean ink outlines, flat cel shading with soft gradients, hand-painted anime background art. ")
GPT_STYLE_TAIL = (" Style lock: every person and object is drawn in the same 2D anime style with clean outlines — "
                  "not a photograph, not photorealistic, not live action, not a 3D CG render, no realistic skin texture.")
_GPT_SWAP = [("realistic adult proportions", "natural adult proportions"),
             ("individually rendered hair strands with glossy light sheen", "hair drawn in clean anime strands with soft highlights"),
             ("Hyper-detailed luminous painted background", "Richly detailed luminous hand-painted anime background"),
             ("soft lens flare and ", ""), ("cinematic", "anime-film")]


def _gpt_prompt(prompt: str) -> str:
    for a, b in _GPT_SWAP:
        prompt = prompt.replace(a, b)
    return GPT_STYLE_HEAD + prompt + GPT_STYLE_TAIL


def _gpt_image(key: str, prompt: str, aspect: str, dest: str, quality: str = "medium") -> None:
    """OpenAI 이미지 생성 (공식: POST /v1/images/generations → data[0].b64_json). JPG 로 저장."""
    import base64
    import io
    import requests
    from PIL import Image
    body = {"model": GPT_IMAGE_MODEL, "prompt": _gpt_prompt(prompt)[:30000], "size": GPT_SIZES.get(aspect, "1536x864"),
            "quality": quality or "medium", "n": 1}
    r = None
    for attempt in range(3):                       # 429(요청 과다)만 쉬었다 다시
        r = requests.post("https://api.openai.com/v1/images/generations", json=body, timeout=300,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        if r.status_code != 429:
            break
        time.sleep(20 * (attempt + 1))
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"GPT Image {r.status_code}: {msg}")
    d = (r.json().get("data") or [{}])[0]
    if d.get("b64_json"):
        raw = base64.b64decode(d["b64_json"])
    elif d.get("url"):
        raw = requests.get(d["url"], timeout=120).content
    else:
        raise RuntimeError("GPT Image 응답에 그림이 없습니다")
    Image.open(io.BytesIO(raw)).convert("RGB").save(dest, "JPEG", quality=94)


def paint(keys: dict, prompt: str, aspect: str, dest: str, state: dict = None, cover: bool = False) -> str:
    """그림 한 장. OPENAI_API_KEY 가 있으면 GPT Image 2, 없거나 실패하면 flux-dev. 쓴 모델 이름을 돌려준다."""
    ok = keys.get("OPENAI_API_KEY", "")
    if ok:
        try:
            q = (keys.get("OPENAI_COVER_QUALITY") or "high") if cover else (keys.get("OPENAI_IMAGE_QUALITY") or "medium")
            _gpt_image(ok, prompt, aspect, dest, q.strip().lower())   # 표지는 클릭을 좌우해서 기본 high
            return GPT_IMAGE_MODEL
        except Exception as e:
            print(f"[rodoku] GPT Image 실패 → flux-dev: {e}", flush=True)
            if state is not None:
                state["gpt_image_error"] = str(e)[:300]
    hz._download(hz.generate_image(keys.get("REPLICATE_API_TOKEN", ""), prompt, aspect=aspect), dest)
    return "flux-dev"


HEROINE_AGE = ("She is an elegant, beautiful woman in her mid-fifties, like the graceful heroine of a mature josei anime: "
               "a slim refined figure, a slender oval face with clear bright eyes, soft natural makeup, faint laugh lines only at the corners of the eyes, "
               "a few fine silver strands in her neatly styled hair, graceful upright posture. Attractive and dignified, clearly an adult woman, "
               "not a girl, not plump, not a plain housewife character. ")   # 2026-11-09: 썸네일 주인공은 채널 배너처럼 예쁜 50대 (가마쿠라 편 반응 > 금붕어 편의 평범한 체형)


_PLAIN_LOOK = re.compile(r"\s*(,|;|\band\b)?\s*(a\s+)?((calm|mature|soft|gentle|sturdy)\s+)*(slightly\s+|a bit\s+)?(fuller|plump|chubby|stocky|heavy[- ]set|rounder)\s+(figure|cheeks|face|build|body)", re.I)


def _slim_look(look: str) -> str:
    """예전 설계의 '통통한 체형' 문구를 지운다 (다시 그리기 때도 배너처럼 예쁜 50대로)."""
    t = _PLAIN_LOOK.sub("", look or "")
    t = re.sub(r"\s*([;,])(\s*[;,])+", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip().strip(";,").strip().rstrip(".")


def _scene_body(plan: dict, c: dict, k: int, sc: dict) -> str:
    body = (sc.get("image_prompt") or c.get("image_prompt") or "").strip().rstrip(".") + "."
    if "red" not in body.lower():
        body += f" {(plan.get('red_accent') or 'A thin red thread').strip().rstrip('.')} in vivid vermilion red."
    if k == 0 and c["no"] == _cover_no(plan):
        body += " " + cover_light(plan)
    hr = plan.get("heroine") or {}
    if sc.get("with_hero") and hr.get("look_en"):
        # 나이는 맨 앞에 둔다 — 그림 모델은 앞쪽 단어를 더 강하게 따르고, 애니풍은 기본으로 얼굴을 젊게 그린다
        age = hr.get("age") or 56
        body = (f"Main character: a Japanese woman aged {age} (not a girl, not a young woman). {HEROINE_AGE}"
                f"{_slim_look(hr['look_en'])}. Her face is visible with one clear quiet expression. " + body)
    yw = plan.get("young_woman") or {}
    if sc.get("with_young") and yw.get("look_en"):
        body += f" The young Japanese woman in her twenties: {yw['look_en'].strip().rstrip('.')}. Her face is visible."
    return body


def _draw_scene(state, keys, ak, plan, c, k, sc, name):
    """장면 그림 하나: 그리기 → 검수 → 떨어지면 다시 (최대 MAX_IMAGE_TRIES). 스레드에서 돈다."""
    body = _scene_body(plan, c, k, sc)
    prompt = ART_PREFIX + " " + body + ART_SUFFIX
    dest = pf(state, name)
    tries = []
    for attempt in range(MAX_IMAGE_TRIES):
        cand = dest.replace(".jpg", f"_try{attempt + 1}.jpg")
        model = paint(keys, prompt, "16:9", cand, state, cover=(k == 0 and c["no"] == _cover_no(plan)))   # 표지 장 = 본편 섬네일 바탕 → high
        rv = inspect_image(ak, cand, {"no": c["no"], "image_prompt": body}, plan)
        tries.append((cand, rv))
        if rv.get("ok"):
            break
    best = min(tries, key=lambda t: (not t[1].get("ok"), len(t[1].get("problems") or [])))
    shutil.copyfile(best[0], dest)
    sc.setdefault("image", {}).update(local=dest, review=best[1], tries=len(tries), model=model,
                                      r2_key=keep(keys, state, dest, name, "image/jpeg"))


# 움직임 검수는 '움직이다 생긴 일그러짐'만 본다. 그림 자체의 화풍·나이·소품 지적은 정지 그림 검수에서 이미 통과했으므로
# 여기서 다시 떨어뜨리지 않는다 (2026-11-09: 금붕어 편 18컷 중 9컷이 "hand-drawn"의 hand, "youthful face"의 face 에 걸려 정지 그림이 됨).
_MOTION_BREAK = re.compile(r"\b(hands?|fingers?|arms?|legs?|eyes?|faces?|anatom\w*|limbs?|fused|melt\w*|morph\w*|distort\w*|warp\w*|deform\w*|extra)\b(?!-drawn)", re.I)
_NOT_MOTION = re.compile(r"3D|\bCG\b|render|photo|style|hand-drawn|young|youthful|twenties|teen|girl|\bage\b|aged|older|description|contrary|text|letter|writing|diary|sign", re.I)


def _motion_breakage(problem: str) -> bool:
    return bool(_MOTION_BREAK.search(problem)) and not _NOT_MOTION.search(problem)


def _motion_defect(keys, clip: str, scene: str, plan: dict) -> list:
    """움직임 영상의 중간·끝 장면 두 장을 이어 붙여 Claude 에게 손·팔·얼굴이 일그러졌는지 본다. 문제 목록(없으면 [])."""
    try:
        dur = hz.duration(clip) or 6.0
        sheet = clip.replace(".mp4", "_check.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{dur * 0.5:.2f}", "-i", clip, "-ss", f"{dur * 0.92:.2f}",
                        "-i", clip, "-filter_complex", "[0:v]scale=-2:540,trim=end_frame=1[a];[1:v]scale=-2:540,trim=end_frame=1[b];"
                        "[a][b]hstack=inputs=2[v]", "-map", "[v]", "-frames:v", "1", "-q:v", "3", sheet],
                       check=True, timeout=120)
        rv = inspect_image(keys.get("ANTHROPIC_API_KEY", ""), sheet,
                           {"image_prompt": f"(two frames of one animated clip, side by side) {scene}"}, plan)
        try:
            os.remove(sheet)
        except OSError:
            pass
        if rv.get("ok"):
            return []
        return [p for p in rv.get("problems") or [] if _motion_breakage(p)]
    except Exception as e:
        print(f"[rodoku] 움직임 검수 실패 → 통과 처리: {e}", flush=True)
        return []


def _motion_one(state, keys, c, k, sc):
    from src.video_replicate import generate_single_clip_url
    mo = sc.setdefault("motion", {})
    name = f"ch{c['no']:02d}_motion.mp4" if k == 0 else f"ch{c['no']:02d}_s{k + 1}_motion.mp4"
    img = hz.ensure_local(keys, sc.get("image") or {}, pf(state, f"ch{c['no']:02d}.jpg" if k == 0 else f"ch{c['no']:02d}_s{k + 1}.jpg"))
    if not img:
        return
    mo.pop("error", None)
    prompt = ((sc.get("motion_prompt") or MOTION_FALLBACK).strip().rstrip(".") +
              ". Static locked-off camera, no camera movement, no zoom, no pan, no cuts. The people stay in "
              "place, only the small repeating elements move. Hands, fingers and arms stay completely still and "
              "unchanged — do not animate hands. Keep the hand-drawn animation look. No text.")
    dest = pf(state, name)
    try:
        url = generate_single_clip_url(keys.get("REPLICATE_API_TOKEN", ""), prompt, image_url=img, prompt_optimizer=False)
        hz._download(url, dest)
        bad = _motion_defect(keys, dest, sc.get("image_prompt") or c.get("image_prompt", ""), state.get("plan") or {})
        if bad:   # 움직이다 손·얼굴이 일그러진 영상은 버리고, 검수를 통과한 정지 그림(Ken Burns)으로
            os.remove(dest)
            mo["rejected"] = True   # 다시 이어 만들 때 또 만들지 않는다 (비용)
            mo["error"] = f"움직임 검수 탈락 → 정지 그림 사용: {'; '.join(bad)}"[:300]
            print(f"[rodoku] 제{c['no']}장 장면{k + 1} {mo['error']}", flush=True)
            return
        mo.update(local=dest, prompt=prompt, r2_key=keep(keys, state, dest, name, "video/mp4"))
    except Exception as e:
        mo["error"] = f"{type(e).__name__}: {e}"[:300]
        print(f"[rodoku] 제{c['no']}장 장면{k + 1} 움직임 실패 → Ken Burns: {e}", flush=True)


# ── 낭독용 숫자 정리 (TTS 가 이상하게 읽지 않게) ──
_KD = "〇一二三四五六七八九"


def _kanji_num(n: int) -> str:
    """정수 → 위치 한자 (1989 → 千九百八十九, 20000 → 二万)."""
    if n == 0:
        return "零"
    def under(m):
        out = ""
        for v, u in ((1000, "千"), (100, "百"), (10, "十")):
            d, m = divmod(m, v)
            if d:
                out += ("" if d == 1 else _KD[d]) + u
        return out + (_KD[m] if m else "")
    out = ""
    for v, u in ((10 ** 8, "億"), (10 ** 4, "万")):
        d, n = divmod(n, v)
        if d:
            out += under(d) + u
    return out + (under(n) if n else "")


def speakable(t: str) -> str:
    """낭독 직전 숫자 정리: 아라비아 숫자 → 한자, 「一九八九年」 같은 한 자씩 연도 → 「千九百八十九年」."""
    if not t:
        return t
    def num(m):
        d = m.group(0).replace(",", "")
        if (d.startswith("0") and len(d) > 1) or len(d) > 12:     # 0 으로 시작하는 번호는 한 자씩
            return "".join(_KD[int(ch)] for ch in d)
        return _kanji_num(int(d))
    t = re.sub(r"\d{1,3}(?:,\d{3})+|\d+", num, t)
    t = re.sub(r"([〇一二三四五六七八九]{3,4})(?=年)", lambda m: _kanji_num(int("".join(str(_KD.index(ch)) for ch in m.group(1)))), t)
    return t


# ── 배역 목소리 ──
CAST_ROLES = {"hero": "주인공 (52~68세 여성)", "partner": "상대 남성 · 현재 (남편·옛 연인 등)",
              "partner_young": "상대 남성 · 회상 (젊은 시절)", "young": "젊은 여성 (20대)"}
CAST_SAMPLE = {"hero": "あの人、まだ覚えていてくれたのね。", "partner": "久しぶりだな。元気にしてたか。",
               "partner_young": "君のことが大好きだ。",
               "young": "おばあちゃん、これ、誰の手紙？"}
# 기본 배역 (2026-11-05 ElevenLabs 오디션으로 Claude 가 고름 · 화면에서 바꿔 저장하면 그 값이 우선)
DEFAULT_VOICES = {"hero": "jWxWvPtq4PJFwe66Y9xi",      # Ado — 성숙·차분, 낭독자(Satomi)와 음색이 겹치지 않음
                  "partner": "C6EwdDpfpjUWhKn1xeaG",   # Makoto 誠 — 60대 남성, 깊고 침착
                  "partner_young": "ScPQKLRUjviCkw0qP47u",  # Takayuki Ito — 젊고 깊은 중저음 (회상 장면)
                  "young": "pdJqk51tDVoes2IzwOyU"}     # Kiyomi — 30대, 차분하고 따뜻한 대화체
VOICES_KEY = "scenestory/_voices.json"
_VOICES_LOCAL = os.path.join("projects", "_rodoku_voices.json")


def load_voices(keys: dict) -> dict:
    d = {}
    try:
        if os.path.exists(_VOICES_LOCAL):
            d = json.load(open(_VOICES_LOCAL, encoding="utf-8"))
    except Exception:
        d = {}
    if hz._r2_ok(keys):
        try:
            from src import r2_store
            d.update(r2_store.get_json(keys, VOICES_KEY) or {})
        except Exception:
            pass
    return {k: str(d.get(k, "")).strip() or DEFAULT_VOICES.get(k, "") for k in CAST_ROLES}


def save_voices(keys: dict, d: dict) -> None:
    d = {k: str(d.get(k, "")).strip() for k in CAST_ROLES}
    os.makedirs(os.path.dirname(_VOICES_LOCAL), exist_ok=True)
    json.dump(d, open(_VOICES_LOCAL, "w", encoding="utf-8"), ensure_ascii=False)
    if hz._r2_ok(keys):
        try:
            from src import r2_store
            r2_store.put_json(keys, VOICES_KEY, d)
        except Exception as e:
            print(f"[rodoku] 배역 목소리 저장 실패: {e}", flush=True)


SPEAKER_SYSTEM = """あなたは朗読ドラマの演出家です。本文の「」の台詞それぞれについて、誰が話しているかを決めます。
役は次の5つだけ:
- hero（主人公の女性）
- partner（相手役の男性が「現在」の場面で話す台詞）
- partner_young（同じ相手役の男性が「回想・過去」の場面＝若い頃に話す台詞。年号や「あの頃」「若い頃」などで回想とわかる場面）
- young（20代の若い女性）
- narrator（それ以外の人物・手紙や看板の文言・心の声）
JSONだけを出力: {"speakers": ["hero", "narrator", ...]}  （台詞の数と同じ長さ、登場順）"""


def _segments(text: str, speakers: list) -> list:
    """本文 → [(役, 文)]。「」の中だけ役の声、それ以外は narrator。"""
    out, pos, i = [], 0, 0
    for m in re.finditer(r"「([^「」]+)」", text):
        if m.start() > pos:
            out.append(("narrator", text[pos:m.start()]))
        role = speakers[i] if i < len(speakers) else "narrator"
        out.append((role if role in CAST_ROLES else "narrator", m.group(1)))
        pos, i = m.end(), i + 1
    if pos < len(text):
        out.append(("narrator", text[pos:]))
    merged = []
    for role, t in out:
        t = t.strip()
        if not re.sub(r"[\s。、]", "", t):
            continue
        if merged and merged[-1][0] == role:
            merged[-1] = (role, merged[-1][1] + t)
        else:
            merged.append((role, t))
    return merged


def _voice_for(role: str, cast: dict, narrator: str) -> str:
    """배역 → 목소리. 회상 상대역이 비어 있으면 현재 상대역, 그것도 없으면 낭독자."""
    if role == "partner_young":
        return cast.get("partner_young") or cast.get("partner") or narrator
    return cast.get(role) or narrator


def cast_narration(keys: dict, ak: str, state: dict, c: dict, head: str, dest: str, narrator: str, cast: dict) -> str:
    """지문은 낭독자 목소리, 대사는 배역 목소리로 따로 읽어 하나로 잇는다. 배역 지정이 실패하면 전부 낭독자."""
    from concurrent.futures import ThreadPoolExecutor
    from src.audio import generate_narration
    text = c.get("text", "")
    n_q = len(re.findall(r"「[^「」]+」", text))
    if "speakers" not in c:
        try:
            names = [f"{ch.get('name', '')}（{ch.get('role', '')}）" for ch in (state["plan"].get("characters") or [])]
            yw = state["plan"].get("young_woman") or {}
            user = (f"登場人物: {', '.join(names)} / 若い女性: {yw.get('name', '')}（{yw.get('role', '')}）\n"
                    f"台詞の数: {n_q}\n\n[本文]\n{text}")
            c["speakers"] = (_json_call(ak, SPEAKER_SYSTEM, user, 1500).get("speakers") or [])[:n_q] if n_q else []
        except Exception as e:
            print(f"[rodoku] 제{c['no']}장 배역 나누기 실패 → 낭독자 혼자: {e}", flush=True)
            c["speakers"] = []
    segs = _segments(text, c["speakers"])
    if not head.strip():
        pass                                    # 쇼츠: 장 제목 없이 바로 본문(대사)부터
    elif segs and segs[0][0] == "narrator":
        segs[0] = ("narrator", head.strip() + segs[0][1])
    else:
        segs.insert(0, ("narrator", head.strip()))
    tmpdir = os.path.dirname(pf(state, "cast", f"ch{c['no']:02d}", "x"))
    files = [os.path.join(tmpdir, f"{i:03d}.mp3") for i in range(len(segs))]

    def one(i):
        role, t = segs[i]
        if hz.usable(files[i]):
            return
        generate_narration(keys.get("ELEVENLABS_API_KEY", ""), speakable(t), files[i], voice_id=_voice_for(role, cast, narrator), info={})
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(one, range(len(segs))))
    # 목소리마다 규격(채널·표본율)이 다를 수 있어 모두 같은 WAV 로 맞춘 뒤 잇는다
    wavs = []
    for fp in files:
        w = fp.replace(".mp3", ".wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", fp, "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", w],
                       check=True, timeout=120)
        wavs.append(w)
    gap = os.path.join(tmpdir, "gap.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "0.25", "-i", "anullsrc=r=44100:cl=mono",
                    "-c:a", "pcm_s16le", gap], check=True, timeout=60)
    lst = os.path.join(tmpdir, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for i, fp in enumerate(wavs):
            if i:
                f.write(f"file '{os.path.abspath(gap)}'\n")
            f.write(f"file '{os.path.abspath(fp)}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-ar", "44100", "-ac", "1",
                    "-c:a", "libmp3lame", "-b:a", "128k", dest], check=True, timeout=600)
    c["cast_segments"] = len(segs)
    return dest


def _make_motion(job, state, keys, save_fn):
    """그림 한 장 → MiniMax 6초 움직임 클립. state['motion_on'] 이 False 면 건너뛴다(Ken Burns)."""
    if state.get("motion_on") is False:
        return
    todo = []
    for c in state["chapters"]:
        for k, sc in enumerate([c] + list(c.get("extra") or [])):
            if not (sc.get("image") or {}).get("local") and not (sc.get("image") or {}).get("r2_key"):
                continue
            name = f"ch{c['no']:02d}_motion.mp4" if k == 0 else f"ch{c['no']:02d}_s{k + 1}_motion.mp4"
            mo = sc.setdefault("motion", {})
            if not mo.get("rejected") and not hz.ensure_local(keys, mo, pf(state, name)):
                todo.append((c, k, sc))
    if not todo:
        return
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _stage(job, state, save_fn, "motion", 4, f"움직임 {len(todo)}개 (MiniMax, 3개씩 동시에)")
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(_motion_one, state, keys, c, k, sc): (c, k) for c, k, sc in todo}
        for f in as_completed(futs):
            c, k = futs[f]
            done += 1
            _stage(job, state, save_fn, "motion", 4, f"움직임 {done}/{len(todo)} · 제{c['no']}장 장면{k + 1}")


def build_anime_loop(raw: str, out: str) -> str:
    """6초 움직임 클립 → 초당 7.5장으로 줄여 손그림 애니메이션 느낌 → 앞으로+거꾸로 이어 끊김 없는 약 12초 루프."""
    n = max(int(hz.duration(raw) * ANIME_FPS), 4)
    vf = (f"[0:v]fps={ANIME_FPS},split[f][b];[b]reverse,trim=start_frame=1:end_frame={n - 1},setpts=PTS-STARTPTS[r];"
          f"[f][r]concat=n=2:v=1:a=0,fps={hz.FPS},{hz.FILL},format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-filter_complex", vf, "-map", "[v]",
                    *X264_FAST, "-crf", "20", "-an", "-movflags", "+faststart", out], check=True, timeout=900)
    return out


MAX_IMAGE_TRIES = 3
INSPECT_SYSTEM = """You are the quality checker for illustrations in a Japanese narrated drama on YouTube.
Look at the image and check ONLY these hard defects:
1. anatomy: extra or missing arms, legs, fingers or eyes; fused or melted hands; a twisted or broken face
2. text: readable or garbled letters, numbers or signboard writing anywhere in the image
3. scene: the image clearly does not match the scene description (wrong place, indoor drawn as outdoor, wrong number of people)
4. elderly faces: a clearly very old person (seventy or older, white hair, deep wrinkles) has the face shown from the front. A woman in her fifties showing her face is fine, even with silver strands and laugh lines (that is the main character).
5. age: the description says the main woman is in her fifties, but she is drawn as a young woman (teens to early thirties, smooth youthful face, no gray hair)
6. weather: rain is falling while the sky is clear blue and sunny (rain must come from a gray sky)
7. style: the image looks like a photograph, a live-action film frame or a 3D CG render instead of a 2D hand-drawn anime illustration with clean outlines and cel shading
Small stylistic differences are fine. Output JSON only: {"ok": true or false, "problems": ["short English description", ...]}"""


def inspect_image(api_key: str, path: str, ch: dict, plan: dict) -> dict:
    """Claude 가 그림을 보고 팔·손가락·눈 개수, 글자, 장면 불일치를 검사. 검사를 못 하면 통과로 본다."""
    import base64
    from src.prompts import SCRIPT_MODEL, _text_of, _extract_json
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        scene = ch.get("image_prompt", "")
        resp = _claude(api_key).messages.create(
            model=SCRIPT_MODEL, max_tokens=400, system=INSPECT_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": f"Scene description: {scene}\nJSON only."}]}])
        txt = _text_of(resp)
        try:
            rv = _extract_json(txt)
        except Exception:
            # 「Extra data」: JSON 뒤에 설명이 붙어 온 경우 — 첫 JSON 객체만 읽는다
            i = txt.find("{")
            rv = json.JSONDecoder().raw_decode(txt[i:])[0] if i >= 0 else {}
        return {"ok": bool(rv.get("ok")), "problems": [str(p)[:120] for p in (rv.get("problems") or [])][:5]}
    except Exception as e:
        print(f"[rodoku] 그림 검수 실패 → 통과 처리: {e}", flush=True)
        return {"ok": True, "problems": [], "skipped": True}


def _speech_timeline(state, audio_parts) -> list:
    """완성 영상에서 각 낭독 파일이 시작하는 시각 + 그 낭독의 원문 (자막 파일용)."""
    kanji = "一二三四五六七八九十"
    texts = {}
    for c in state.get("chapters") or []:
        au = (c.get("audio") or {}).get("local")
        if au:
            texts[au] = f"第{kanji[c['no'] - 1] if c['no'] <= 10 else c['no']}章、{c['title_ja']}。\n\n{c.get('text', '')}"
    for key, txt in (("cold", None), ("intro", None), ("outro", OUTRO_JA)):
        it = state.get(key) or {}
        if it.get("local"):
            texts[it["local"]] = txt or it.get("text", "")
    out, cur = [], 0.0
    for kind, val in audio_parts:
        if kind == "silence":
            cur += float(val)
            continue
        d = hz.duration(val)
        out.append({"start": round(cur, 3), "seconds": round(d, 3), "audio": val, "text": texts.get(val, "")})
        cur += d
    return out


AMB_VOLUME = 0.18      # 환경음 (낭독을 가리지 않게 낮게)


def _make_ambience(job, state, keys, save_fn):
    """장마다 환경음 30초 (끊김 없이 반복되는 소리). 실패한 장은 환경음 없이."""
    from elevenlabs import ElevenLabs
    for c in state["chapters"]:
        it = c.setdefault("ambience", {})
        txt = (c.get("ambience_en") or "").strip()
        dest = pf(state, "amb", f"ch{c['no']:02d}.mp3")
        if not txt or hz.ensure_local(keys, it, dest) or it.get("error"):
            continue
        _stage(job, state, save_fn, "music", 6, f"제{c['no']}장 환경음")
        prompt = txt.rstrip(".") + ". Ambient background sound only, no voices, no music."
        try:
            cl = ElevenLabs(api_key=keys.get("ELEVENLABS_API_KEY", ""))
            try:
                gen = cl.text_to_sound_effects.convert(text=prompt, duration_seconds=30, loop=True, prompt_influence=0.5)
            except TypeError:           # 예전 SDK 는 loop 를 모른다
                gen = cl.text_to_sound_effects.convert(text=prompt, duration_seconds=30, prompt_influence=0.5)
            with open(dest, "wb") as f:
                for ch in gen:
                    if ch:
                        f.write(ch)
            if not hz.usable(dest):
                raise RuntimeError("빈 소리")
            it.update(local=dest, prompt=prompt, r2_key=keep(keys, state, dest, f"amb_ch{c['no']:02d}.mp3", "audio/mpeg"))
        except Exception as e:
            it["error"] = f"{type(e).__name__}: {e}"[:200]
            print(f"[rodoku] 제{c['no']}장 환경음 실패 → 생략: {e}", flush=True)
        hz._save(save_fn, state)


def _ambience_bed(state, spans, total) -> str:
    """장 구간마다 그 장의 환경음을 반복해 깔고, 나머지(첫머리·마무리)는 무음인 한 줄짜리 소리."""
    pieces, cur = [], 0.0
    d = os.path.dirname(pf(state, "work", "amb", "x"))
    for i, (a, b, c) in enumerate(spans):
        src = (c.get("ambience") or {}).get("local", "")
        if not hz.usable(src):
            continue
        if a > cur + 0.01:
            pieces.append(("sil", a - cur))
        pieces.append((src, b - a))
        cur = b
    if not any(p[0] != "sil" for p in pieces):
        return ""
    if total > cur + 0.01:
        pieces.append(("sil", total - cur))
    files = []
    for i, (src, dur) in enumerate(pieces):
        out = os.path.join(d, f"p{i:02d}.wav")
        if src == "sil":
            cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo", out]
        else:
            cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", src, "-t", f"{dur:.3f}", "-af",
                   f"aresample=44100,aformat=channel_layouts=stereo,afade=t=in:d=2,afade=t=out:st={max(dur - 2, 0):.2f}:d=2",
                   "-c:a", "pcm_s16le", out]
        subprocess.run(cmd, check=True, timeout=300)
        files.append(out)
    lst = os.path.join(d, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for fp in files:
            f.write(f"file '{os.path.abspath(fp)}'\n")
    bed = os.path.join(d, "bed.m4a")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "aac", "-b:a", "128k", bed],
                   check=True, timeout=600)
    return bed


def _render(job, state, keys, save_fn):
    chs = state["chapters"]
    segs, audio_parts, marks = [], [], []
    # 오프닝 카드 (1장 그림 · 작품 제목)
    loops, scene_loops, amb_spans = {}, {}, []
    for c in chs:
        scene_loops[c["no"]] = []
        for k, sc in enumerate([c] + list(c.get("extra") or [])):
            tag = f"{c['no']:02d}" + ("" if k == 0 else f"_s{k + 1}")
            img = hz.ensure_local(keys, sc.get("image") or {}, pf(state, f"ch{tag}.jpg"))
            if not img:
                continue
            raw = hz.ensure_local(keys, sc.get("motion") or {}, pf(state, f"ch{tag}_motion.mp4"))
            lp = pf(state, "work", f"loop{tag}{'_anime' if raw else ''}.mp4")
            if not hz.usable(lp):
                job["msg"] = f"[8/10] 합성 · 제{c['no']}장 장면{k + 1} 화면 루프 ({'움직임' if raw else 'Ken Burns'})"
                if raw:
                    try:
                        build_anime_loop(raw, lp)
                    except Exception as e:
                        print(f"[rodoku] 제{c['no']}장 장면{k + 1} 움직임 루프 실패 → Ken Burns: {e}", flush=True)
                        lp = pf(state, "work", f"loop{tag}.mp4")
                if not hz.usable(lp):
                    hz.build_kenburns_loop(img, lp, base=(2560, 1440), x264=X264_FAST)   # 4K 대신 2.5K 에서 줌 → 계산량 약 절반
            scene_loops[c["no"]].append(lp)
        loops[c["no"]] = scene_loops[c["no"]][0]
    title = state["plan"].get("title_ja", "")
    t = 0.0
    cold = state.get("cold") or {}
    if hz.usable(cold.get("local", "")):   # 콜드 오픈: 반전 장 화면 + 자막 + 낭독 → 그다음 제목
        try:
            tno = int(state["plan"].get("turn_chapter") or 0)
        except (TypeError, ValueError):
            tno = 0
        tloop = loops.get(tno) or loops[chs[max(len(chs) - 2, 0)]["no"]]
        csec = (cold.get("seconds") or hz.duration(cold["local"])) + 1.8
        segs.append(_caption_clip(tloop, cold["text"], csec, 0.6, csec - 1.8, pf(state, "work", "seg_cold.mp4")))
        audio_parts += [("silence", 0.6), ("file", cold["local"]), ("silence", 1.2)]
        t = csec
    op = _card_clip(loops[1], _card_png(pf(state, "work", "open.png"), title, "SceneStory 朗読ドラマ"),
                    OPEN_CARD_SEC, pf(state, "work", "seg_open.mp4"))
    segs.append(op)
    audio_parts.append(("silence", OPEN_CARD_SEC))
    t += OPEN_CARD_SEC
    intro = state.get("intro") or {}
    if hz.usable(intro.get("local", "")):   # 화자의 앞말: 1장 화면 + 자막 + 낭독 → 第一章
        isec = (intro.get("seconds") or hz.duration(intro["local"])) + 1.6
        segs.append(_caption_clip(loops[chs[0]["no"]], intro["text"], isec, 0.4, isec - 1.6, pf(state, "work", "seg_intro.mp4")))
        audio_parts += [("silence", 0.4), ("file", intro["local"]), ("silence", 1.2)]
        t += isec
    kanji = "一二三四五六七八九十"
    sub_spans = []
    for c in chs:
        job["msg"] = f"[8/10] 합성 · 제{c['no']}장 이어 붙이는 중"
        a = c["audio"]["seconds"] or hz.duration(c["audio"]["local"])
        seg_len = a + CHAPTER_PAD_SEC
        card = _card_png(pf(state, "work", f"t{c['no']:02d}.png"), c["title_ja"],
                         f"第{kanji[c['no'] - 1] if c['no'] <= 10 else c['no']}章")
        segs.append(_card_clip(loops[c["no"]], card, TITLE_CARD_SEC, pf(state, "work", f"seg{c['no']:02d}a.mp4")))
        body = max(seg_len - TITLE_CARD_SEC, 0.5)
        sl = scene_loops[c["no"]]
        if len(sl) <= 1 or body < 20:
            segs.append(_body_clip(loops[c["no"]], TITLE_CARD_SEC, body, pf(state, "work", f"seg{c['no']:02d}b.mp4")))
        else:                                   # 장면 수만큼 고르게 나눠 그림을 바꾼다 (첫 장면은 제목 카드 시간만큼 짧게)
            part = (body + TITLE_CARD_SEC) / len(sl)
            for k, lp in enumerate(sl):
                d = (part - TITLE_CARD_SEC) if k == 0 else (body - (part - TITLE_CARD_SEC) - part * (len(sl) - 2) if k == len(sl) - 1 else part)
                segs.append(_body_clip(lp, 0, max(d, 0.5), pf(state, "work", f"seg{c['no']:02d}b{k + 1}.mp4")))
        marks.append((t, f"第{kanji[c['no'] - 1] if c['no'] <= 10 else c['no']}章 {c['title_ja']}"))
        sub_spans.append((t, c))
        amb_spans.append((t, t + max(seg_len, TITLE_CARD_SEC + 0.5), c))
        audio_parts.append(("file", c["audio"]["local"]))
        audio_parts.append(("silence", CHAPTER_PAD_SEC))
        t += max(seg_len, TITLE_CARD_SEC + 0.5)
    ou = state.get("outro") or {}
    if hz.usable(ou.get("local", "")):
        oa = ou.get("seconds") or hz.duration(ou["local"])
        osec = max(oa + 2.5, ENDSCREEN_SEC)     # YouTube 종료 화면(마지막 5~20초)을 놓을 자리 — 다음 편으로 이어 보게
        card = _endcard_png(pf(state, "work", "outro.png"))
        segs.append(_outro_clip(loops[chs[-1]["no"]], card, osec, pf(state, "work", "seg_outro.mp4")))
        marks.append((t, "おわりに"))
        audio_parts.append(("silence", 0.8))
        audio_parts.append(("file", ou["local"]))
        audio_parts.append(("silence", osec - 0.8 - oa))
        t += osec
    total = t
    lst = pf(state, "work", "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"file '{os.path.abspath(s)}'\n")
    video = pf(state, "work", "video.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", video],
                   check=True, timeout=900)
    if SUBS_ON and state.get("subs_on", True):
        video = _burn_subs(state, keys, job, video, sub_spans, total, save_fn)
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
    n_in = k + (2 if ga and gb else 1 if (ga or gb) else 0)
    amb = _ambience_bed(state, amb_spans, total)
    if amb:
        args += ["-i", amb]
        fc += f";[{n_in}:a]aresample=44100,aformat=channel_layouts=stereo,volume={AMB_VOLUME}[amb]"
    mix = ["[narr]"] + (["[bg]"] if (ga or gb) else []) + (["[amb]"] if amb else [])
    if len(mix) > 1:
        fc += f";{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0[mx]"
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
            "chapters": [[round(a, 2), b] for a, b in marks], "made_at": time.strftime("%Y-%m-%d %H:%M"),
            "speech": _speech_timeline(state, audio_parts)}
    job["msg"] = f"[8/10] 합성 · R2 에 올리는 중 ({info['bytes'] / 1e6:.0f}MB)"
    info["r2_key"] = keep(keys, state, final, os.path.basename(final), "video/mp4")
    state["final"] = info
    hz._save(save_fn, state)


N_SHORTS = 3          # 최대
DEFAULT_SHORTS = 3    # 2026-11-07: 쇼츠 1개 ≈ 1천 회(28일 데이터) → 한 편에서 장면이 다른 쇼츠 3개 (화면에서 1로 바꿀 수 있음)
DEFAULT_SCENES = 3    # 장마다 그림 수 (1~3)
SHORT_ANGLES = [
    "",   # 1번: 자유 — 続きを聴きたくなる一節
    "今回は物語の始まりから選ぶ。人物と状況が一瞬で伝わり、この人に何が起きるのかと気になる一節。",
    "今回は反転の直前から選ぶ。何かが明かされそうで明かされない、緊張がいちばん高い一節。",
]


_NORM_DROP = set("　 \n\t、。，．,.!！?？「」『』（）()…・ー―－-〜~:：;；\"'")


def _norm_ja(t: str) -> str:
    return "".join(ch for ch in speakable(t or "") if ch not in _NORM_DROP)


def excerpt_from_main(keys: dict, c: dict, excerpt: str, dest: str) -> float:
    """쇼츠 대목을 본편 장 낭독에서 잘라 쓴다 (ElevenLabs 크레딧 0, 목소리도 본편과 똑같음).
    c['subs'] = [[글자, 시작, 끝], ...] (장 낭독 기준 초, 본편 자막 맞추기 때 저장된 것)를 이어 붙여 대목의 위치를 찾는다.
    잘라 낸 길이(초)를 돌려주고, 못 찾으면 0."""
    subs = c.get("subs") or []
    if not subs or not (c.get("audio") or {}).get("local") and not (c.get("audio") or {}).get("r2_key"):
        return 0.0
    want = _norm_ja(excerpt)
    if len(want) < 8:
        return 0.0
    joined, spans = "", []
    for txt, a, b in subs:
        n = _norm_ja(txt)
        spans.append((len(joined), len(joined) + len(n), float(a), float(b)))
        joined += n
    i = joined.find(want)
    if i < 0:                                    # 대목 끝이 조금 다르게 다듬어졌을 수 있다 → 앞 70% 로 다시
        head = want[: max(8, int(len(want) * 0.7))]
        i = joined.find(head)
        if i < 0:
            return 0.0
    j = i + len(want)
    a = next((sa for s0, s1, sa, sb in spans if s0 <= i < s1), None)
    b = next((sb for s0, s1, sa, sb in spans if s0 < j <= s1), spans[-1][3] if j >= len(joined) else None)
    if a is None or b is None or b - a < 3:
        return 0.0
    src_au = hz.ensure_local(keys, c["audio"], c["audio"].get("local") or dest + ".src.mp3")
    if not src_au:
        return 0.0
    start, end = max(0.0, a - 0.15), b + 0.35
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src_au,
                    "-af", "afade=t=in:d=0.08,afade=t=out:st=" + f"{max(0.0, end - start - 0.25):.3f}" + ":d=0.25",
                    "-c:a", "libmp3lame", "-b:a", "192k", dest], check=True, timeout=120)
    return round(end - start, 2) if hz.usable(dest) else 0.0


HOOK_FACE_SEC = 1.6   # 쇼츠 첫 장면: 주인공 얼굴 클로즈업 (2026-11-11: 뒷모습으로 시작한 쇼츠 6시간 28회 vs 평소 1천 회)


def _hook_face(state, keys, folder: str, pick: dict, c: dict) -> str:
    """쇼츠 첫 1.6초용 세로 얼굴 클로즈업 그림. 검수 2번까지, 실패하면 ''(기존처럼 장면 영상으로 시작)."""
    plan = state.get("plan") or {}
    hr = plan.get("heroine") or {}
    if not hr.get("look_en"):
        return ""
    face = (pick.get("face_en") or "her eyes wide and lips slightly parted in stunned silence").strip().rstrip(".")
    place = ((plan.get("setting") or {}).get("place") or "").strip()
    body = (f"Vertical close-up portrait. Her face and shoulders fill the lower two thirds of the frame, the top of her head "
            f"at about one third from the top; the top third of the frame is soft out-of-focus background with no detail. Main character: a Japanese woman aged {hr.get('age') or 56} "
            f"(not a girl, not a young woman). {HEROINE_AGE}{_slim_look(hr['look_en'])}. {face}. "
            f"Background: {place or 'a quiet Japanese room'}, softly blurred. One person only.")
    prompt = ART_PREFIX + " " + body + ART_SUFFIX
    dest = pf(state, folder, "hook_face.jpg")
    for attempt in range(2):
        try:
            paint(keys, prompt, "9:16", dest, state)
            rv = inspect_image(keys.get("ANTHROPIC_API_KEY", ""), dest, {"no": c.get("no", 0), "image_prompt": body}, plan)
            if rv.get("ok"):
                try:   # 글자 없는 얼굴 그림도 R2 에 남겨 '클라우드 완성 파일 받기'에서 받을 수 있게 (표지 직접 교체용)
                    keep(keys, state, dest, f"{folder}_face.jpg", "image/jpeg")
                except Exception:
                    pass
                return dest
            print(f"[rodoku] 쇼츠 얼굴 그림 검수 탈락 {attempt + 1}/2: {(rv.get('problems') or [''])[0][:120]}", flush=True)
        except Exception as e:
            print(f"[rodoku] 쇼츠 얼굴 그림 실패: {e}", flush=True)
            return ""
    return ""


def _face_opener(image: str, rest: str, out: str, sec_rest: float) -> str:
    """얼굴 그림 1.6초(천천히 다가감) + 기존 장면 영상을 이어 붙인다. 실패하면 기존 영상 그대로."""
    try:
        n = int(HOOK_FACE_SEC * hz.FPS)
        op = out.replace(".mp4", "_face.mp4")
        vf = (f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,scale=2160:3840,"
              f"zoompan=z='1.0+0.06*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps={hz.FPS},"
              f"setsar=1,format=yuv420p")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(hz.FPS), "-i", image, "-vf", vf,
                        "-frames:v", str(n), *X264_FAST, "-crf", "20", "-an", op], check=True, timeout=300)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", op, "-t", f"{sec_rest:.2f}", "-i", rest, "-filter_complex",
                        f"[0:v]fps={hz.FPS},setsar=1,format=yuv420p[a];[1:v]fps={hz.FPS},scale=1080:1920,setsar=1,format=yuv420p[b];"
                        "[a][b]concat=n=2:v=1:a=0[v]", "-map", "[v]", *X264_FAST, "-crf", "20", "-an", out],
                       check=True, timeout=600)
        return out if hz.usable(out) else rest
    except Exception as e:
        print(f"[rodoku] 얼굴 첫 장면 붙이기 실패 → 장면 영상으로 시작: {e}", flush=True)
        return rest


def _end_tease(video: str, text: str, sec: float, out: str) -> str:
    """예고 쇼츠 마지막 2.2초에 '다음이 궁금한 질문'을 화면 가운데 띄운다 (2026-11-14). 실패하면 원래 영상."""
    try:
        from PIL import Image, ImageDraw
        from src.scenestory import jp_font, JP_SANS_BOLD
        png = out.replace(".mp4", ".png")
        im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        # 마지막 자막 자리(아래쪽)를 덮어 질문만 보이게 (2026-11-14 『千本鳥居』: 질문과 마지막 자막이 위아래로 겹쳐 읽힘)
        d.rectangle((0, 1330, 1080, 1730), fill=(14, 10, 9, 240))
        f = jp_font(JP_SANS_BOLD, 84)
        lines = [text]
        if d.textlength(text, font=f) > 1000:
            marks = [i for i, ch in enumerate(text) if ch in "、，" and 3 < i < len(text) - 3]
            if not marks:
                marks = [i for i, ch in enumerate(text) if ch in "はがをにでとも" and 3 < i < len(text) - 3]
            if not marks:
                marks = [i for i, ch in enumerate(text) if ch == "の" and 3 < i < len(text) - 3]
            cut = min(marks, key=lambda i: abs(i - len(text) / 2)) if marks else len(text) // 2
            lines = [text[:cut + 1], text[cut + 1:]]
            while max(d.textlength(x, font=f) for x in lines) > 1020 and f.size > 60:
                f = jp_font(JP_SANS_BOLD, f.size - 4)
        y0 = 1530 - int(f.size * 0.6 * len(lines))
        for i, ln in enumerate(lines):
            d.text((540, y0 + i * int(f.size * 1.2)), ln, font=f, fill=(255, 226, 120, 255), anchor="mt", stroke_width=7,
                   stroke_fill=(20, 14, 12, 255))
        im.save(png)
        st = max(sec - 2.2, 0)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-loop", "1", "-i", png, "-filter_complex",
                        f"[1:v]format=rgba,fade=t=in:st={st:.2f}:d=0.25:alpha=1[t];[0:v][t]overlay=0:0:shortest=1:enable='gte(t,{st:.2f})',format=yuv420p[v]",
                        "-map", "[v]", "-t", f"{sec:.2f}", *X264_FAST, "-crf", "20", "-an", out], check=True, timeout=600)
        return out if hz.usable(out) else video
    except Exception as e:
        print(f"[rodoku] 끝 질문 붙이기 실패 → 그대로: {e}", flush=True)
        return video


def _quiet_points(au: str) -> list:
    """낭독 사이 숨 쉬는 자리(0.3초 이상 조용한 곳)의 가운데 시각들. 장면을 바꿀 자리로 쓴다."""
    try:
        r = subprocess.run(["ffmpeg", "-v", "info", "-i", au, "-af", "silencedetect=n=-35dB:d=0.3", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120)
        st = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", r.stderr)]
        en = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", r.stderr)]
        return [(a + b) / 2 for a, b in zip(st, en)]
    except Exception:
        return []


def _teaser_recut(vloop: str, still: str, face: str, au: str, sec: float, out: str) -> str:
    """예고 쇼츠가 한 장면으로 30초 넘게 이어지지 않게 (2026-11-14 『A-17の里芋』: 37초 동안 같은 그림).
    움직임 장면 → 같은 장 그림을 인물 쪽으로 다가가며 → 첫 장면 얼굴로 천천히 물러나며 (끝이 처음과 이어져 반복 재생에도 자연스럽다).
    바꾸는 자리는 낭독이 숨 쉬는 곳. 실패하면 원래 영상 그대로."""
    try:
        body = sec - HOOK_FACE_SEC
        if body < 18 or not still:
            return vloop
        qs = [q - HOOK_FACE_SEC for q in _quiet_points(au)]
        def near(t):
            ok = [q for q in qs if 5 < q < body - 4]
            return min(ok, key=lambda q: abs(q - t)) if ok else t
        c1 = near(body * 0.42)
        c2 = near(body * 0.75) if face else body
        if c2 - c1 < 4:
            c2 = body if not face else min(body - 4, c1 + 6)
        tmp = os.path.dirname(out)
        n2 = max(int((c2 - c1 + 0.5) * hz.FPS), 2)
        s2 = os.path.join(tmp, "cut_still.mp4")
        # 가로 그림 전체를 가운데 크게(인물이 한쪽에 있어도 잘리지 않게) + 뒤는 같은 그림을 흐리게 채움, 천천히 다가감
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(hz.FPS), "-i", still, "-filter_complex",
                        f"[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                        f"boxblur=28:2,eq=brightness=-0.10[bg];"
                        f"[b]scale=2880:-2,zoompan=z='1.0+0.08*on/{n2}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                        f"d=1:s=1440x810:fps={hz.FPS},crop=1180:810[fg];"
                        f"[bg]fps={hz.FPS}[bg2];[bg2][fg]overlay=(W-w)/2:470:shortest=1,setsar=1,format=yuv420p[v]",
                        "-map", "[v]", "-frames:v", str(n2), *X264_FAST, "-crf", "20", "-an", s2], check=True, timeout=300)
        parts = [(vloop, c1), (s2, c2 - c1)]
        if face and body - c2 > 2:
            n3 = max(int((body - c2 + 1) * hz.FPS), 2)
            s3 = os.path.join(tmp, "cut_face.mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(hz.FPS), "-i", face, "-vf",
                            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,scale=2160:3840,"
                            f"zoompan=z='1.16-0.10*on/{n3}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps={hz.FPS},"
                            f"setsar=1,format=yuv420p", "-frames:v", str(n3), *X264_FAST, "-crf", "20", "-an", s3],
                           check=True, timeout=300)
            parts.append((s3, body - c2 + 1))
        ins, fc = [], ""
        for i, (v, ln) in enumerate(parts):
            ins += ["-t", f"{ln:.2f}", "-i", v]
            fc += f"[{i}:v]fps={hz.FPS},scale=1080:1920,setsar=1,format=yuv420p[v{i}];"
        fc += "".join(f"[v{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
        subprocess.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", fc, "-map", "[v]", *X264_FAST,
                        "-crf", "20", "-an", out], check=True, timeout=600)
        if hz.usable(out):
            print(f"[rodoku] 예고 쇼츠 장면 나눔: {c1:.1f}s / {c2:.1f}s 에서 바꿈", flush=True)
            return out
        return vloop
    except Exception as e:
        print(f"[rodoku] 예고 쇼츠 장면 나누기 실패 → 한 장면 그대로: {e}", flush=True)
        return vloop


COMPLETE_SYSTEM = """あなたは朗読ドラマの60秒ショートの編集者です。本編の全文から、短い3か所をそのまま抜き出し、つなげて一話完結の60秒にします。
2026-11-12: 続きが気になるだけの予告ショートは、見た人の反応（高評価・コメント）が0.4%しかなかった。見下された主人公が最後に品よく報われる流れを60秒で完結させる。
① blow: 主人公が受ける一撃。見下す台詞・突き放す宣告。ショートの最初の1秒になるので、いちばん強い一文から始める。
② turn: 形勢が変わる瞬間。隠していた物・事実が明かされる。
③ last: 結末で主人公が言う品のある一言、またはそれを受けた相手の沈黙。勝ち誇らない。
各か所は本文から一字も変えずに1〜3文。3か所の合計は空白を除いて220〜330字（60秒以内）。設計に short_lines があればそれを含む文を優先する。
JSONだけを出力: {"parts": [{"role": "blow", "chapter": 章番号, "excerpt": "本文そのまま"}, {"role": "turn", ...}, {"role": "last", ...}],
"hook_line": "①の台詞を「」付きで14字以内に縮めたもの", "face_en": "①を聞いた瞬間の主人公（50代の女性）の顔を英語で一文。表情は一つだけ断定",
"shorts_title": "台詞「」を先頭に、年数か金額を入れた30字以内の題"}"""


def _complete_short(job, state, keys, folder: str):
    """한 편 안에서 완결되는 60초 쇼츠의 재료: 본편 낭독 세 군데를 잘라 잇는다 (크레딧 0). 못 만들면 None."""
    chs = state["chapters"]
    plan = state.get("plan") or {}
    full = "\n\n".join(f"第{c['no']}章\n{c['text']}" for c in chs)
    hint = json.dumps(plan.get("short_lines") or [], ensure_ascii=False)
    pick = _json_call(keys.get("ANTHROPIC_API_KEY", ""), COMPLETE_SYSTEM, f"[設計 short_lines]\n{hint}\n\n{full}", max_tokens=2000)
    parts = [x for x in (pick.get("parts") or []) if isinstance(x, dict) and (x.get("excerpt") or "").strip()][:3]
    if len(parts) < 3:
        return None
    tmp = pf(state, folder, "x").rsplit("/", 1)[0]
    segs = []
    for i, x in enumerate(parts):
        ex = x["excerpt"].strip()
        c = next((y for y in chs if y["no"] == _int0(x.get("chapter")) and ex[:12] in y.get("text", "")),
                 next((y for y in chs if ex[:12] in y.get("text", "")), None))
        if not c:
            return None
        a = os.path.join(tmp, f"part{i}.mp3")
        if excerpt_from_main(keys, c, ex, a) <= 0:
            return None
        segs.append((c, ex, a, hz.duration(a)))
    gap = os.path.join(tmp, "gap.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.45",
                    "-c:a", "libmp3lame", gap], check=True, timeout=60)
    lst = os.path.join(tmp, "parts.txt")
    with open(lst, "w") as f:
        for i, sg in enumerate(segs):
            f.write(f"file '{sg[2]}'\n" + (f"file '{gap}'\n" if i < len(segs) - 1 else ""))
    au = pf(state, folder, "voice.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "192k", au],
                   check=True, timeout=120)
    if hz.duration(au) > 62:
        print(f"[rodoku] 완결형 쇼츠가 {hz.duration(au):.0f}초로 길어 예고형으로 만듭니다.", flush=True)
        return None
    # 그림: 세 대목 각자의 장 그림(움직임 우선)을 그 길이만큼 이어 붙인다
    clips = []
    for i, (c, ex, a, d) in enumerate(segs):
        ln = d + (0.45 if i < len(segs) - 1 else 1.5)
        raw = hz.ensure_local(keys, c.get("motion") or {}, pf(state, f"ch{c['no']:02d}_motion.mp4"))
        v = ""
        if raw:
            try:
                v = _vertical_anime(raw, os.path.join(tmp, f"vl{i}.mp4"), sec=int(ln) + 1)
            except Exception:
                v = ""
        if not v:
            v = _vertical_loop(c["image"]["local"], os.path.join(tmp, f"vl{i}.mp4"), sec=int(ln) + 1)
        clips.append((v, ln))
    vloop = os.path.join(tmp, "vloop_complete.mp4")
    ins, fc = [], ""
    for i, (v, ln) in enumerate(clips):
        ins += ["-t", f"{ln:.2f}", "-i", v]
        fc += f"[{i}:v]fps={hz.FPS},scale=1080:1920,setsar=1,format=yuv420p[v{i}];"
    fc += "".join(f"[v{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[v]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", fc, "-map", "[v]", *X264_FAST, "-crf", "20", "-an", vloop],
                   check=True, timeout=900)
    pick["excerpt"] = "\n".join(sg[1] for sg in segs)
    return {"pick": pick, "audio": au, "vloop": vloop, "chapter": segs[0][0]["no"], "c": segs[0][0],
            "chapters": [sg[0]["no"] for sg in segs]}


def _trailer(job, state, keys, slot: int = 0):
    """예고 쇼츠 slot 번째 (0: state['trailer'], 1·2: state['trailers'][slot-1]). 장면이 겹치지 않게 고른다."""
    from src.audio import generate_narration
    from src import captions as cap
    from src.assembler import render_scene_clip
    chs = state["chapters"]
    folder = "trailer" if slot == 0 else f"trailer{slot + 1}"
    used = [t.get("chapter") for t in [state.get("trailer") or {}] + (state.get("trailers") or []) if t.get("chapter")]
    pool = chs[:-1]                                                         # 마지막 장(결말)은 빼고 고른다
    if slot == 1:
        pool = chs[:2]
    elif slot == 2:
        try:
            tno = int(state["plan"].get("turn_chapter") or 0)
        except (TypeError, ValueError):
            tno = 0
        pool = [c for c in chs if c["no"] == max(tno - 1, 1)] or chs[-3:-1]
    if slot:
        pool = [c for c in pool if c["no"] not in used] or pool
    done = None
    if slot == 2 and state.get("complete_short_on", True):
        job["msg"] = "쇼츠 3: 60초 완결형 만드는 중"
        try:
            done = _complete_short(job, state, keys, folder)
        except Exception as e:
            print(f"[rodoku] 완결형 쇼츠 실패 → 예고형: {e}", flush=True)
            done = None
    if done:
        return _finish_short(job, state, keys, slot, folder, done["pick"], done["c"], done["audio"], done["vloop"],
                             kind="complete", chapters=done["chapters"])
    full = "\n\n".join(f"第{c['no']}章\n{c['text']}" for c in pool)
    if SHORT_ANGLES[slot]:
        full = SHORT_ANGLES[slot] + "\n\n" + full
    if is_sukatto((state.get("plan") or {}).get("kind", "")) and slot in (0, 1):
        # 통쾌편: 무시하는 한마디가 가장 강한 미끼 → 첫 1초에 그 대사, 화면 위 문구도 그 대사
        full = ("今回はスカッと系。相手が主人公を見下す決定的な台詞（「」）を含む文から抜き出しを始める（最初の一文がその台詞）。"
                "hook_line はその台詞そのものを「」付きで14字以内に縮めたもの（例：「家にいるだけで楽でいいな」）。"
                "shorts_title も台詞を「」で先頭に置き、年数などの数字を入れる。\n\n" + full)
    pick = _json_call(keys.get("ANTHROPIC_API_KEY", ""), TRAILER_SYSTEM, full, max_tokens=1500)
    excerpt = (pick.get("excerpt") or "").strip()
    if not excerpt:
        raise ValueError("예고 대목을 고르지 못했습니다.")
    try:
        no = int(pick.get("chapter") or 0)
    except (TypeError, ValueError):
        no = 0
    c = next((x for x in pool if x["no"] == no), next((x for x in pool if excerpt[:20] in x.get("text", "")), pool[0]))
    no = c["no"]
    voice = keys.get("ELEVENLABS_VOICE_ID_JA") or JA_VOICE_ID
    au = pf(state, folder, "voice.mp3")
    cast = state.get("cast_voices") or {}
    voiced = False
    try:
        # 1순위: 본편 낭독에서 그 대목을 잘라 쓴다 (크레딧 0 · 본편과 같은 배역 목소리)
        voiced = excerpt_from_main(keys, c, excerpt, au) > 0
        if voiced:
            print(f"[rodoku] 쇼츠 목소리: 본편 제{no}장 낭독에서 잘라 씀", flush=True)
    except Exception as e:
        print(f"[rodoku] 본편 낭독 자르기 실패 → 새로 낭독: {e}", flush=True)
    if not voiced and cast and "「" in excerpt:
        # 쇼츠도 본편처럼 대사는 인물 목소리로 — 첫 1초의 무시하는 한마디가 낭독자 목소리면 힘이 빠진다
        # (2026-11-08 「あなたたちのものでは」 쇼츠: 계속 시청 55.2% / 이탈 44.8% → 첫 1초 보강)
        try:
            import shutil
            pc = {"no": 90 + slot, "text": excerpt}
            shutil.rmtree(os.path.dirname(pf(state, "cast", f"ch{90 + slot:02d}", "x")), ignore_errors=True)
            cast_narration(keys, keys.get("ANTHROPIC_API_KEY", ""), state, pc, "", au, voice, cast)
            voiced = hz.usable(au)
        except Exception as e:
            print(f"[rodoku] 쇼츠 배역 목소리 실패 → 낭독자 혼자: {e}", flush=True)
    if not voiced:
        generate_narration(keys.get("ELEVENLABS_API_KEY", ""), speakable(excerpt), au, voice_id=voice)
    sec = min(hz.duration(au) + 1.5, 58.0)
    tmp = pf(state, folder, "x").rsplit("/", 1)[0]
    raw = hz.ensure_local(keys, c.get("motion") or {}, pf(state, f"ch{c['no']:02d}_motion.mp4"))
    vloop = ""
    if raw:
        try:
            vloop = _vertical_anime(raw, os.path.join(tmp, "vloop.mp4"), sec=int(sec) + 1)
        except Exception as e:
            print(f"[rodoku] 예고편 움직임 실패 → Ken Burns: {e}", flush=True)
    if not vloop:
        vloop = _vertical_loop(c["image"]["local"], os.path.join(tmp, "vloop.mp4"), sec=int(sec) + 1)
    return _finish_short(job, state, keys, slot, folder, pick, c, au, vloop)


def _finish_short(job, state, keys, slot, folder, pick, c, au, vloop, kind="teaser", chapters=None):
    """얼굴 첫 장면 + 위 문구 + 자막 + 소리를 합쳐 쇼츠를 완성하고 state 에 넣는다."""
    from src import captions as cap
    from src.assembler import render_scene_clip
    excerpt = pick.get("excerpt", "")
    no = c["no"]
    tease = (pick.get("end_tease") or "").strip() if kind == "teaser" else ""
    sec = min(hz.duration(au) + (2.6 if tease else 1.5), 62.0)
    tmp = pf(state, folder, "x").rsplit("/", 1)[0]
    face_img = ""
    if state.get("hook_face_on", True):
        job["msg"] = f"쇼츠 {slot + 1} 첫 장면 얼굴 그리는 중"
        face_img = _hook_face(state, keys, folder, pick, c)
    if kind == "teaser":
        vloop = _teaser_recut(vloop, (c.get("image") or {}).get("local", ""), face_img, au, sec,
                              os.path.join(tmp, "vloop_cuts.mp4"))
    if state.get("hook_face_on", True):
        if face_img:
            vloop = _face_opener(face_img, vloop, os.path.join(tmp, "vloop_face.mp4"), sec - HOOK_FACE_SEC + 1)
    top = os.path.join(tmp, "top.png")
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SERIF_BOLD, JP_SANS_BOLD
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((540, 150), "SceneStory 朗読ドラマ", font=jp_font(JP_SERIF_BOLD, 40), fill=(227, 181, 164, 255), anchor="ma",
           stroke_width=3, stroke_fill=(20, 14, 12, 255))
    d.text((540, 230), pick.get("hook_line") or state["plan"].get("title_ja", ""), font=jp_font(JP_SANS_BOLD, 76),
           fill=(255, 244, 234, 255), anchor="ma", stroke_width=6, stroke_fill=(20, 14, 12, 255))
    d.text((540, 1780), "ここまでの物語は本編で ▼ 下のリンクから" if kind == "complete" else "続きは本編で ▼ 下のリンクから",
           font=jp_font(JP_SANS_BOLD, 44), fill=(227, 181, 164, 255), anchor="ma",
           stroke_width=4, stroke_fill=(20, 14, 12, 255))
    im.save(top)
    caps = cap.build_for_scene({"narration": excerpt}, sec, tmp, 1, 1080, 1920, lang="ja", instant=True)
    silent = os.path.join(tmp, "v.mp4")
    render_scene_clip(vloop, top, sec, silent, instant=True, captions=caps, punch_in=False)
    if tease:
        silent = _end_tease(silent, tease, sec, os.path.join(tmp, "v_tease.mp4"))
    out = pf(state, folder, "trailer.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", au, "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-t", f"{sec:.2f}",
                    "-movflags", "+faststart", out], check=True, timeout=600)
    item = {"local": out, "seconds": round(sec, 1), "chapter": no, "excerpt": excerpt,
                        "hook_line": pick.get("hook_line", ""), "shorts_title": pick.get("shorts_title", ""),
                        "face_opener": bool(face_img), "kind": kind, "chapters": chapters or [no],
                        "r2_key": keep(keys, state, out, f"{folder}.mp4", "video/mp4")}
    if slot == 0:
        state["trailer"] = item
    else:
        lst = state.setdefault("trailers", [])
        while len(lst) < slot:
            lst.append({})
        lst[slot - 1] = item


COVER_SKY = ("Bright daytime outdoors under a clear saturated cobalt-blue sky with towering white cumulus clouds, "
             "lush green trees, sunlight sparkling, fresh and hopeful mood.")


def cover_light(plan: dict) -> str:
    """표지의 빛·날씨. 설계에 지역·날씨가 있으면 그것, 없으면(예전 편) 파란 하늘."""
    if plan.get("weather_en"):
        return (f"Bright daytime outdoors in {plan.get('region_en', 'Japan')}, {plan['weather_en']}, "
                "luminous and inviting, never dark or gloomy.")
    return COVER_SKY


def _cover_no(plan: dict) -> int:
    try:
        return int(plan.get("cover_chapter") or 0)
    except (TypeError, ValueError):
        return 0


def cover_scene(plan: dict) -> str:
    """표지(본편 섬네일·쇼츠 표지)용 야외 장면 — 실내 장면은 클릭이 적다(작가 판단). 설계에 없으면 기본 장면을 만든다."""
    yw = plan.get("young_woman") or {}
    hr = plan.get("heroine") or {}
    red = (plan.get("red_accent") or "a thin red thread").strip().rstrip(".")
    sc = (plan.get("cover_scene") or "").strip().rstrip(".")
    if hr.get("look_en"):   # 50대 주인공이 표지의 얼굴 (2026-11 작가 결정: 50대로 시청층 확대)
        if not sc:
            sc = f"A Japanese woman in her fifties stands on a quiet seaside road holding {red}"
        if hr["look_en"][:30] not in sc:
            sc += f". Her look: {_slim_look(hr['look_en'])}. Her face is visible with one quiet expression"
        sc = (f"Main character: a Japanese woman aged {hr.get('age') or 56} (not a girl, not a young woman). {HEROINE_AGE}" + sc)
    else:                   # 예전 설계 (주인공 외형이 없던 편)
        if not sc:
            sc = f"A young Japanese woman in her twenties walks along a quiet seaside road holding {red}"
        if yw.get("look_en") and yw["look_en"][:30] not in sc:
            sc += f". The young woman: {yw['look_en'].strip().rstrip('.')}. Her face is visible"
    if "red" not in sc.lower():
        sc += f". {red} in vivid vermilion red"
    return sc + ". " + cover_light(plan)


def _cover_image(state, keys, aspect: str, dest: str) -> str:
    """표지용 야외 그림을 새로 그린다 (검수 통과 못 하면 한 번 더). 실패하면 ''."""
    plan = state["plan"]
    body = cover_scene(plan)
    head = ART_PREFIX if aspect == "16:9" else ART_PREFIX.replace("wide cinematic 16:9 composition",
                                                                  "tall vertical 9:16 poster composition")
    tail = (" Composition: the woman is small in the frame and stands in the bottom third, her head at about 70 percent of the "
            "frame height from the top; the middle band of the frame (from 30 to 65 percent height) is empty open sky with "
            "nothing in it, because the title text goes there." if aspect == "9:16"
            else " The woman stands on the right third of the frame, open sky on the upper left.")
    prompt = head + " " + body + tail + ART_SUFFIX
    tries = []
    try:
        for attempt in range(3):   # 표지는 클릭을 좌우해서 한 번 더 (50대가 젊게 그려지면 다시)
            cand = dest.replace(".jpg", f"_try{attempt + 1}.jpg")
            paint(keys, prompt, aspect, cand, state, cover=True)
            rv = inspect_image(keys.get("ANTHROPIC_API_KEY", ""), cand, {"no": 0, "image_prompt": body}, plan)
            tries.append((cand, rv))
            if rv.get("ok"):
                break
        shutil.copyfile(min(tries, key=lambda t: (not t[1].get("ok"), len(t[1].get("problems") or [])))[0], dest)
        return dest
    except Exception as e:
        print(f"[rodoku] 표지 그림({aspect}) 실패: {e}", flush=True)
        return ""


def _shorts_cover(state, keys, slot: int = 0):
    """예고 쇼츠 표지 1080×1920 — 영상에서 뽑은 장면이 아니라 표지용 세로 그림을 새로 그려 글자를 얹는다.
    쇼츠 표지는 목록에서 가운데 3:2 정도만 보이므로 글자는 화면 가운데 띠 안에 둔다."""
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SERIF_BOLD, JP_SANS_BOLD, phrase_wrap
    plan = state["plan"]
    trl = state["trailer"] if slot == 0 else state["trailers"][slot - 1]
    folder = "trailer" if slot == 0 else f"trailer{slot + 1}"
    c = next((x for x in state["chapters"] if x["no"] == trl.get("chapter")), state["chapters"][0])
    base = pf(state, folder, "cover_base.jpg")
    face = pf(state, folder, "hook_face.jpg")
    if trl.get("face_opener") and hz.usable(face):
        # 2026-11-11: 표지 글자 띠가 인물 얼굴을 가림 → 쇼츠 첫 장면과 같은 얼굴 클로즈업을 표지로 (위 1/3 은 비워 그린 그림)
        shutil.copyfile(face, base)
    elif not _cover_image(state, keys, "9:16", base):   # 야외 그림을 못 그리면 그 장 그림을 세로로 잘라 쓴다
        shutil.copyfile(c["image"]["local"], base)
    W, H = 1080, 1920
    im = Image.open(base).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((l, t, l + W, t + H))
    if trl.get("face_opener") and hz.usable(face):
        # 얼굴 그림이 위 1/3 을 비우지 않고 그려졌을 때를 대비: 그림을 520px 내려 얼굴을 띠 아래에 두고, 위는 흐린 배경으로 채운다
        from PIL import ImageFilter
        bg = im.filter(ImageFilter.GaussianBlur(28))
        bg.paste(im.crop((0, 0, W, H - 520)), (0, 520))
        im = bg
    im = im.convert("RGBA")
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    ink, cream, rose = (20, 14, 12, 255), (255, 244, 234, 255), (227, 181, 164, 255)
    # 위쪽 띠 (화면 위 9~36%): 얼굴은 그 아래에 그대로 보이게. 예전엔 가운데(32~65%)라 얼굴을 덮었다
    top_y, bot_y = 170, 690
    for y in range(0, bot_y + 140):
        a = 150 if y <= bot_y else int(150 * (1 - (y - bot_y) / 140))
        d.line([(0, y), (W, y)], fill=(16, 12, 10, a))
    hook = (trl.get("hook_line") or plan.get("title_ja", "")).strip()
    lines, f_hook = _quote_lines(d, hook, JP_SANS_BOLD, jp_font, W - 100, min_one=64)
    lh = int(f_hook.size * 1.25)
    y = top_y + 60
    d.text((W // 2, y), "朗読ドラマ", font=jp_font(JP_SERIF_BOLD, 44), fill=rose, anchor="ma")
    y += 90
    for ln in lines[:3]:
        d.text((W // 2, y), ln, font=f_hook, fill=cream, anchor="ma", stroke_width=5, stroke_fill=ink)
        y += lh
    y += 24
    d.text((W // 2, y), f"『{plan.get('title_ja', '')}』", font=jp_font(JP_SERIF_BOLD, 54), fill=rose, anchor="ma",
           stroke_width=3, stroke_fill=ink)
    d.text((W // 2, H - 150), "SceneStory", font=jp_font(JP_SERIF_BOLD, 40), fill=rose, anchor="ma",
           stroke_width=3, stroke_fill=ink)
    out = pf(state, folder, "cover_1080x1920.jpg")
    Image.alpha_composite(im, over).convert("RGB").save(out, "JPEG", quality=92)
    trl["cover"] = {"local": out, "r2_key": keep(keys, state, out, f"{folder}_cover.jpg", "image/jpeg")}


# ── 자막 파일 (.srt) — YouTube 에 '자막'으로 따로 올린다. 영상에 굽지 않으므로 다시 합성할 필요가 없다 ──
SUBTITLES_ON = False   # True 로 바꾸면 매 편 일본어 자막 파일(.srt)을 만든다
SRT_MAX = 26     # 한 줄 최대 글자 수 (일본어)


def _align(keys: dict, audio: str, text: str) -> list:
    """ElevenLabs Forced Alignment → [(글자, 시작, 끝)]. 실패하면 글자 수 비례로 나눈다."""
    clean = re.sub(r"\s+", "", text)
    try:
        import requests
        with open(audio, "rb") as f:
            r = requests.post("https://api.elevenlabs.io/v1/forced-alignment",
                              headers={"xi-api-key": keys.get("ELEVENLABS_API_KEY", "")},
                              files={"file": (os.path.basename(audio), f, "audio/mpeg")}, data={"text": text}, timeout=300)
        r.raise_for_status()
        chars = [(str(c.get("text", "")), float(c.get("start", 0)), float(c.get("end", 0)))
                 for c in (r.json().get("characters") or [])]
        chars = [c for c in chars if c[0].strip()]
        if len(chars) >= len(clean) * 0.8:
            return chars
        print(f"[rodoku] 자막 맞추기 결과가 짧음 ({len(chars)}/{len(clean)}) → 비례 배분", flush=True)
    except Exception as e:
        print(f"[rodoku] 자막 맞추기 실패 → 비례 배분: {e}", flush=True)
    d = hz.duration(audio) or len(clean) / JA_CPS
    n = max(len(clean), 1)
    return [(ch, i * d / n, (i + 1) * d / n) for i, ch in enumerate(clean)]


def _cues(chars: list) -> list:
    """글자 목록을 자막 한 줄 단위로: 。！？ 에서 끊고, SRT_MAX 를 넘으면 다음 、에서, 많이 넘으면 강제로.
    너무 짧게 남은 꼬리(4자 미만)는 앞줄에 붙인다."""
    out, buf = [], []
    def flush():
        if buf:
            out.append(["".join(c[0] for c in buf), buf[0][1], buf[-1][2]])
            buf.clear()
    for ch in chars:
        buf.append(ch)
        n = len(buf)
        if ch[0] in "。！？!?" or (ch[0] in "、，," and n >= SRT_MAX * 0.7) or n >= SRT_MAX + 12:
            flush()
    flush()
    merged = []
    for t, a, b in out:
        if merged and len(t.strip("。、 ")) < 4 and len(merged[-1][0]) + len(t) <= SRT_MAX + 16:
            merged[-1][0] += t
            merged[-1][2] = b
        else:
            merged.append([t, a, b])
    return [(t, a, b) for t, a, b in merged if t.strip("。、 ")]

def _ts(x: float) -> str:
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def make_srt(state, keys) -> dict:
    fin = state.get("final") or {}
    rows = []
    for sp in fin.get("speech") or []:
        if not sp.get("text") or not hz.usable(sp.get("audio", "")):
            continue
        for t, a, b in _cues(_align(keys, sp["audio"], sp["text"])):
            rows.append((sp["start"] + a, sp["start"] + max(b, a + 0.6), t))
    if not rows:
        return {"error": "자막을 만들 낭독 정보가 없습니다"}
    for i in range(len(rows) - 1):            # 다음 자막과 겹치지 않게
        if rows[i][1] > rows[i + 1][0]:
            rows[i] = (rows[i][0], rows[i + 1][0] - 0.05, rows[i][2])
    out = pf(state, "subtitles_ja.srt")
    with open(out, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(rows, 1):
            f.write(f"{i}\n{_ts(a)} --> {_ts(b)}\n{t}\n\n")
    return {"local": out, "cues": len(rows), "r2_key": keep(keys, state, out, "subtitles_ja.srt", "application/x-subrip")}


# 재생목록 3개 — 감정 주제어 (작가가 YouTube 에 직접 만든 목록 이름과 같게 유지)
PLAYLISTS = {
    "naku": "感動する話｜夫婦・家族の朗読ドラマ",
    "koi": "恋の話｜初恋・再会・大人の恋",
    "natsu": "懐かしい話｜昭和・平成の思い出",
    "suka": "スカッとする話｜品よく逆転する朗読",
}
PLAYLIST_TAG = {"naku": "【感動する話】", "koi": "【恋の話】", "natsu": "【懐かしい話】", "suka": "【スカッとする話】"}
_KIND_PLAYLIST = {
    "初恋・再会": "koi", "新しい恋": "koi", "旅先の出会い": "koi",
    "昔の仲間": "natsu", "味の記憶": "natsu", "店じまい": "natsu", "故郷じまい": "natsu", "隣人": "natsu",
    "遺品整理": "natsu", "動物との暮らし": "natsu", "孫との一日": "natsu",
}


def _playlist_key(plan: dict) -> str:
    kind = (plan or {}).get("kind", "")
    if is_sukatto(kind):
        return "suka"
    return _KIND_PLAYLIST.get(kind, "naku")


def playlist_for(plan: dict) -> str:
    """이야기 종류 → 넣을 재생목록 이름 (4개). 夫婦·家族 계열(嫁と姑·母と娘·介護·子の巣立ち·夫の秘密 등)은 '感動する話'. (작가 분류: 감동편·사랑편·통쾌편·추억편)"""
    return PLAYLISTS[_playlist_key(plan)]


def _short_texts(state, it: dict, k: int) -> None:
    plan, fin = state["plan"], state.get("final") or {}
    it["description"] = (f"{it.get('hook_line', '')}\n\n本編『{plan.get('title_ja', '')}』"
                         f"（{hz.fmt_time(fin.get('seconds', 0), True)}）は画面下のリンクから。\n\n#朗読 #朗読ドラマ #shorts")
    it["comment"] = (f"{it.get('hook_line', '')}\n本編『{plan.get('title_ja', '')}』は、画面下のリンクからお聴きいただけます。")
    it["post_day"] = ["본편 공개 당일", "다른 날 (본편이 없는 날의 쇼츠로)", "다른 날 (본편이 없는 날의 쇼츠로)"][min(k, 2)]


def start_repack(state: dict, keys: dict, save_fn) -> bool:
    """완성된 편의 제목·설명·섬네일만 새 형식으로 다시 만든다 (이미 올린 편 교체용. GPT 그림 1~2장 + 글 1번)."""
    def worker(job, st, ks, sv):
        job["msg"] = "업로드 정보·섬네일 다시 만드는 중"
        st.pop("upload_pack", None)
        _pack(st, ks)
        st["saved_at"] = time.time()
        sv(st)
        save_cloud(ks, st)
        job["msg"] = "완료"
    return hz._start(state["project_id"], "rodoku_pack", "업로드 정보 다시", worker, (state, keys, save_fn))


def start_extra_short(state: dict, keys: dict, save_fn) -> bool:
    """완성된 편에서 다른 장면으로 쇼츠 하나 더 (새 본편 없이 쇼츠만 올리는 날용)."""
    def save_both(s):
        s["saved_at"] = time.time()
        save_fn(s)
        save_cloud(keys, s)
    return hz._start(state["project_id"], "rodoku_short", "쇼츠 하나 더", _extra_short_worker, (state, keys, save_both))


def _extra_short_worker(job, state, keys, save_fn):
    have = [state.get("trailer") or {}] + list(state.get("trailers") or [])
    slot = next((i for i in range(N_SHORTS) if i >= len(have) or not (have[i].get("local") or have[i].get("r2_key"))), None)
    if slot is None:
        raise RuntimeError(f"이 편의 쇼츠는 이미 {N_SHORTS}개입니다.")
    job["msg"] = f"쇼츠 {slot + 1} 만드는 중 (다른 장면에서)"
    _trailer(job, state, keys, slot)
    it = state["trailer"] if slot == 0 else state["trailers"][slot - 1]
    hz._save(save_fn, state)
    job["msg"] = f"쇼츠 {slot + 1} 표지 그리는 중"
    try:
        _shorts_cover(state, keys, slot)
    except Exception as e:
        it["cover"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    _short_texts(state, it, slot)
    hz._save(save_fn, state)
    job["msg"], job["pct"] = f"완료 — 쇼츠 {slot + 1}", 1.0


def _variant(state, n: int, salt: str = "") -> int:
    """편마다 다르게, 같은 편 안에서는 늘 같게 고르는 번호 (섬네일 배치·제목 순서 변주용)."""
    import hashlib
    h = hashlib.md5((str(state.get("project_id", "")) + salt).encode()).hexdigest()
    return int(h[:8], 16) % n


def _thumb_layout(state, keys) -> tuple:
    """섬네일 배치(얼굴 좌우·색·글씨 높이)를 편 순서대로 돌려, 바로 앞 편과 늘 다르게 (2026-11-14: 무작위로 골랐더니
    『A-17の里芋』『千本鳥居の案内人』이 같은 배치로 나란히 나옴). 한 번 정하면 그 편에 저장해 다시 만들기에도 같게."""
    got = state.get("thumb_layout")
    if isinstance(got, list) and len(got) == 3:
        return tuple(got)
    try:
        pid = str(state.get("project_id", ""))
        k = sum(1 for p in cloud_index(keys) if str(p) < pid)
        lay = (k % 2, k % 3, (k // 2) % 3)
    except Exception:
        lay = (_variant(state, 2, "side"), _variant(state, 3, "pal"), _variant(state, 3, "pos"))
    state["thumb_layout"] = list(lay)
    return lay


def _quote_lines(d, text: str, font_path, jp_font, maxw: int, min_one: int = 56):
    """대사는 한 줄이 원칙 (2026-11-13 요청: 줄바꿈 없이 한 줄로). 글씨를 줄여 한 줄에 넣고,
    min_one 보다 작아져야 할 만큼 길 때만 조사·쉼표 뒤에서 2줄로 나눈다."""
    for size in range(124, min_one - 1, -4):
        f = jp_font(font_path, size)
        if d.textlength(text, font=f) <= maxw:
            return [text], f
    cuts = [i + 1 for i, ch in enumerate(text[:-1]) if ch in "、。！？はがをにでもへの…" and 3 <= i + 1 <= len(text) - 3]
    for size in range(110, 50, -4):
        f = jp_font(font_path, size)
        best = None
        for c in cuts:
            ls = [text[:c], text[c:]]
            w = max(d.textlength(x, font=f) for x in ls)
            bal = abs(len(ls[0]) - len(ls[1]))
            if w <= maxw and (best is None or bal < best[0]):
                best = (bal, ls)
        if best:
            return best[1], f
    f = jp_font(font_path, 50)
    return [text], f


def _thumb_v2(state, keys, quote: str, sub: str, base_img: str = "", tag: str = "A",
              label: str = "기본 — 대사 + 얼굴 (상위 채널 형식) · 한 장만 올릴 때는 이것") -> dict:
    """대사형 본편 섬네일 (1280x720): 오른쪽에 주인공 얼굴 크게, 왼쪽에 상대의 대사를 노란 특대 글씨로.
    2026-11-12: 클릭률 2.6% → 시니어 낭독 상위 채널들처럼 '대사 + 얼굴'로. 실패하면 None (예비 섬네일 사용)."""
    from PIL import Image, ImageDraw
    from src.scenestory import jp_font, JP_SANS_BOLD, JP_SERIF_BOLD
    plan = state.get("plan") or {}
    hr = plan.get("heroine") or {}
    quote = (quote or "").strip()
    if not quote or not hr.get("look_en"):
        return None
    suka = is_sukatto(plan.get("kind", ""))
    face = ("calm and dignified, a faint knowing smile, her eyes looking straight at the viewer" if suka
            else "her eyes glistening with held-back tears, lips pressed together, looking straight at the viewer")
    place = ((plan.get("setting") or {}).get("place") or "a quiet Japanese living room").strip()
    # 편마다 배치·색·글씨 높이를 바꾼다 (같은 틀의 섬네일이 줄지어 있으면 '템플릿 대량 생산'으로 보임. 2026-11-13)
    side_i, pal_i, pos_i = _thumb_layout(state, keys)
    right = side_i == 0
    pal = [((255, 226, 84), (196, 48, 40)), ((255, 250, 242), (34, 58, 104)), ((255, 205, 178), (38, 92, 70))][pal_i]
    vpos = ["mid", "high", "low"][pos_i]
    me, other = ("right", "left") if right else ("left", "right")
    body = (f"Main character: a Japanese woman aged {hr.get('age') or 56} (not a girl, not a young woman). {HEROINE_AGE}"
            f"{_slim_look(hr['look_en'])}. Expression: {face}. She is on the {me} half of the frame, framed from the chest up, "
            f"her face large and sharp. The {other} half of the frame is {place}, softly blurred, with no people and no detail. "
            f"Warm light on her face. One person only.")
    prompt = ART_PREFIX + " " + body + ART_SUFFIX
    base = pf(state, "thumb_v2_base.jpg")
    best = base_img if base_img and hz.usable(base_img) else None
    for attempt in range(0 if best else 2):
        cand = base.replace(".jpg", f"_try{attempt + 1}.jpg")
        paint(keys, prompt, "16:9", cand, state, cover=True)
        rv = inspect_image(keys.get("ANTHROPIC_API_KEY", ""), cand, {"no": 0, "image_prompt": body}, plan)
        best = cand
        if rv.get("ok"):
            break
    W, H = 1280, 720
    im = Image.open(best).convert("RGB")
    sc = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * sc), round(im.height * sc)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((l, t, l + W, t + H)).convert("RGBA")
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for i in range(0, 900):                      # 글씨 쪽을 어둡게, 얼굴 쪽은 그대로
        a = 175 if i < 600 else int(175 * (1 - (i - 600) / 300))
        x = i if right else W - 1 - i
        d.line([(x, 0), (x, H)], fill=(12, 8, 6, a))
    ink = (10, 6, 4, 255)
    qcol, boxcol = pal
    lx = 52 if right else W - 52            # 글씨 기준선 (얼굴 반대편)
    anchor = "la" if right else "ra"
    y = 56
    if sub:
        fs = jp_font(JP_SANS_BOLD, 40)
        tw = d.textlength(sub, font=fs)
        bx = 44 if right else W - 44 - tw - 36
        d.rounded_rectangle([bx, y - 6, bx + tw + 36, y + 56], radius=10, fill=boxcol + (235,))
        d.text((bx + 18, y), sub, font=fs, fill=(255, 246, 236, 255))
        y += 96
    lines, fq = _quote_lines(d, quote, JP_SANS_BOLD, jp_font, 700)
    lh = int(fq.size * 1.18)
    block = lh * len(lines[:3])
    y = {"mid": max(y + 10, (H - block) // 2 + 10), "high": y + 30, "low": max(y + 10, H - 130 - block)}[vpos]
    for ln in lines[:3]:
        d.text((lx, y), ln, font=fq, fill=qcol + (255,), anchor=anchor, stroke_width=9, stroke_fill=ink)
        y += lh
    d.text((lx, H - 70), "SceneStory 朗読ドラマ", font=jp_font(JP_SERIF_BOLD, 34), fill=(232, 190, 170, 255),
           anchor=anchor, stroke_width=3, stroke_fill=ink)
    dst = pf(state, f"thumbnail_{tag}.jpg")
    Image.alpha_composite(im, over).convert("RGB").save(dst, quality=93)
    return {"tag": tag, "label": label, "local": dst, "base": best,
            "r2_key": keep(keys, state, dst, f"thumbnail_{tag}.jpg", "image/jpeg")}


def _pack(state, keys):
    plan, fin = state["plan"], state["final"]
    # 섬네일 3종 (YouTube '테스트 및 비교'용) — 그림과 문구를 서로 다르게
    chs = state["chapters"]
    try:
        tno = int(plan.get("turn_chapter") or 0)
    except (TypeError, ValueError):
        tno = 0
    young = next((c for c in chs if (c.get("with_hero") or c.get("with_young")) and (c.get("image") or {}).get("local")), chs[0])
    turn = next((c for c in chs if c["no"] == tno and (c.get("image") or {}).get("local")), chs[-2] if len(chs) > 1 else chs[0])
    trl0 = state.get("trailer") or {}
    hook = trl0.get("hook_line") or plan.get("title_ja", "")
    cch = next((c for c in chs if c["no"] == _cover_no(plan) and (c.get("image") or {}).get("local")), None)
    if cch:                                   # 본편에서 이미 그린 파란 하늘 장을 그대로 섬네일로
        a_src = cch
    else:                                     # 예전 설계(표지 장 지정 없음)만 표지 그림을 따로 그린다
        cov = pf(state, "cover_16x9.jpg")
        if not hz.usable(cov):
            _cover_image(state, keys, "16:9", cov)
        a_src = {"image": {"local": cov}} if hz.usable(cov) else young
    # 세 장은 반드시 서로 다른 그림 (2026-11-12: 표지 장 = 반전 장이면 A·B 가 같은 그림·같은 제목으로 나왔다)
    def _img(x):
        return (x.get("image") or {}).get("local") or ""
    usedimg = {_img(a_src)}
    cands = [turn] + [c for c in chs if c.get("with_hero")] + [c for c in chs if c.get("with_young")] + list(chs)
    b_src = next((c for c in cands if _img(c) and _img(c) not in usedimg), turn)
    usedimg.add(_img(b_src))
    c_src = next((c for c in [chs[0]] + cands if _img(c) and _img(c) not in usedimg), b_src)
    # A 는 업로드 정보(대사)를 만든 뒤 '대사형 섬네일'로 따로 만든다 (2026-11-12: 잘 되는 채널들의 형식)
    variants = [("B", a_src, plan.get("title_ja", ""), "예비 — 파란 하늘 표지 + 작품 제목"),
                ("C", c_src if c_src is not a_src else b_src, hook, "예비 — 다른 장면 + 질문 문구")]
    thumbs = []
    for tag, c, big, label in variants:
        proxy = {"project_id": state["project_id"], "project_dir": state["project_dir"], "image": c["image"], "thumbnail": {}}
        try:
            hz.make_thumbnail(keys, proxy, big, "SCENESTORY · 朗読ドラマ", brand="SceneStory")
            dst = pf(state, f"thumbnail_{tag}.jpg")
            shutil.copyfile(proxy["thumbnail"]["local"], dst)
            thumbs.append({"tag": tag, "label": label, "local": dst,
                           "r2_key": keep(keys, state, dst, f"thumbnail_{tag}.jpg", "image/jpeg")})
        except Exception as e:
            thumbs.append({"tag": tag, "label": label, "error": str(e)[:200]})
    state["thumbnails"] = thumbs
    state["thumbnail"] = next((t for t in thumbs if t.get("local")), {"error": "섬네일을 만들지 못했습니다"})
    pack = {"title": f"【朗読ドラマ】{plan.get('title_ja', '')}｜{plan.get('kind') or '人生の後半'}",
            "description": plan.get("logline_ja", ""),
            "tags": plan.get("seo_keywords") or [], "hashtags": ["#朗読", "#朗読ドラマ", "#人生の後半"]}
    try:
        first = (chs[0].get("text") or "")[:260] if chs else ""
        user = (f"作品: {plan.get('title_ja')}\nあらすじ: {plan.get('logline_ja')}\n検索語: {plan.get('picked_query')}\n"
                f"SEO語: {', '.join(plan.get('seo_keywords') or [])}\n長さ: {hz.fmt_time(fin['seconds'], True)}\n"
                f"題材の型: {plan.get('kind', '')}\n"
                f"第1章の冒頭（謎の入口）:\n{first}\n"
                f"真実・結末（タイトル・説明に書かない）: {plan.get('turn', '')}"
                + (f"\n予告ショートの台詞（題の最初の台詞として一字も変えずに使う）: {hook}" if trl0.get("hook_line") else "")
                + f"\n並び: {'ABC'[_variant(state, 3)]}")
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
    pack.setdefault("pinned_comment", "最後までお聴きくださり、ありがとうございました。\nこのお話で思い出したことがあれば、そっと聞かせてください。")
    pack.setdefault("shorts_comment", f"本編『{plan.get('title_ja', '')}』は画面下のリンクからどうぞ。")
    pack["playlist"] = playlist_for(plan)
    try:
        a = _thumb_v2(state, keys, pack.get("thumb_quote") or hook, pack.get("thumb_sub") or "")
        if a:
            # B·C 도 같은 얼굴 그림에 문구만 바꾼 새 형식 (그림 추가 비용 없음). 예전 형식은 쓰지 않는다 (2026-11-13)
            b = _thumb_v2(state, keys, pack.get("thumb_reply") or "", pack.get("thumb_sub") or "", a["base"], "B",
                          "예비 — 주인공의 한마디 + 얼굴")
            c = _thumb_v2(state, keys, f"『{plan.get('title_ja', '')}』", pack.get("thumb_sub") or "", a["base"], "C",
                          "예비 — 작품 제목 + 얼굴")
            old = {t.get("tag"): t for t in state.get("thumbnails") or []}
            state["thumbnails"] = [a, b or old.get("B"), c or old.get("C")]
            state["thumbnails"] = [t for t in state["thumbnails"] if t]
            state["thumbnail"] = a
    except Exception as e:
        print(f"[rodoku] 대사형 섬네일 실패 → 예비 섬네일 사용: {e}", flush=True)
    tag = PLAYLIST_TAG[_playlist_key(plan)]
    if pack.get("title") and tag not in pack["title"]:
        tb = re.sub(r"^【[^】]*】", "", pack["title"].strip()).strip()
        tail = "【朗読】【シニア】"
        room = 100 - len(tag) - len(tail)
        if len(tb) > room:
            tb = tb[:room - 1].rstrip("、。 ") + "…"
        pack["title"] = tag + tb + tail   # 잘 되는 채널들처럼 장르 꼬리표를 앞에 (2026-11-12)
    trl = state.get("trailer") or {}
    for k, it in enumerate([state.get("trailer") or {}] + list(state.get("trailers") or [])):
        if it.get("local") or it.get("r2_key"):
            _short_texts(state, it, k)
    pack["shorts_description"] = trl.get("description", "")
    tags = [str(t).strip().lstrip("#") for t in pack.get("tags") or [] if str(t).strip()]
    while tags and len(",".join(tags)) > 480:
        tags.pop()
    pack["tags"] = tags
    state["upload_pack"] = pack
    if not SUBTITLES_ON:                      # 작가 결정(2026-11): 지금은 자막 파일을 만들지 않는다
        return
    try:
        state["subtitles"] = make_srt(state, keys)
    except Exception as e:
        state["subtitles"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        print(f"[rodoku] 자막 파일 실패: {e}", flush=True)


def link(keys: dict, item: dict, filename: str = "") -> str:
    if not item or not item.get("r2_key") or not hz._r2_ok(keys):
        return ""
    from src import r2_store
    return r2_store.download_link(keys, item["r2_key"], filename=filename or os.path.basename(item["r2_key"]))
