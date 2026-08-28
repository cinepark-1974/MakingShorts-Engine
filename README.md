# ☕ 너도나도아는커피 | 숏폼 팩토리

> **고정 PC 없이 어디서든** — 노트북, 태블릿, 모바일 브라우저 URL 하나로  
> 유튜브·틱톡·릴스용 커피 숏폼을 **기획부터 완성본까지 완전 자동 생산**하는 시스템

[![Streamlit](https://img.shields.io/badge/Streamlit-Community_Cloud-FF4B4B?logo=streamlit)](https://share.streamlit.io)
[![Claude](https://img.shields.io/badge/Claude-claude--sonnet--4--5-6B4EFF?logo=anthropic)](https://console.anthropic.com)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-TTS-222222)](https://elevenlabs.io)
[![Fal.ai](https://img.shields.io/badge/Fal.ai-Kling_v2.6_Pro-00B4D8)](https://fal.ai)

---

## 전체 처리 흐름

```
브라우저 입력 (챕터 + 주제)
        │
        ▼
[STEP 1] Claude API
  → 12컷 대본 (60~75초) + Kling 영문 프롬프트 + SFX 태그 → JSON 저장
        │
        ▼
[STEP 2] ElevenLabs API
  → 전체 나레이션 텍스트 → 고품질 성우 음성 (MP3)
        │
        ▼
[STEP 3] Fal.ai Kling v2.6 Pro
  → 컷별 영문 프롬프트 → 9:16 세로 영상 (5초/컷) × 12컷
        │
        ▼
[STEP 4] FFmpeg + Whisper
  → 음성 + 영상 + SFX + BGM + 다이나믹 자막 → 최종 숏폼 MP4
```

---

## 디렉터리 구조

```
youandiknowcoffee-shorts-factory/
├── .streamlit/
│   └── secrets.toml.example      # API 키 설정 예시
├── src/
│   ├── __init__.py
│   ├── prompts.py                # Claude API — 12컷 대본 & Kling 프롬프트 생성기
│   ├── audio.py                  # ElevenLabs — 나레이션 음성(MP3) 생성기
│   ├── video_fal.py              # Fal.ai Kling — 컷별 비디오 생성기
│   ├── state_manager.py          # JSON 기반 상태 저장 / 불러오기 / 컷별 재생성
│   └── assembler.py              # FFmpeg + Whisper — 자막·SFX·BGM 합성기
├── assets/
│   └── sfx/                      # whoosh, impact, tech, steam 등 효과음
├── app.py                        # Streamlit 메인 대시보드
├── packages.txt                  # Streamlit Cloud 서버 패키지 (ffmpeg)
├── requirements.txt              # Python 라이브러리 의존성
└── README.md
```

---

## 필요한 API 키 (3종)

| 키 이름 | 용도 | 발급 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 12컷 대본 · Kling 영상 프롬프트 생성 | [console.anthropic.com](https://console.anthropic.com) |
| `ELEVENLABS_API_KEY` | 나레이션 성우 음성 생성 | [elevenlabs.io](https://elevenlabs.io) |
| `FAL_KEY` | Kling v2.6 Pro 비디오 생성 | [fal.ai](https://fal.ai) |

---

## 로컬 실행

### 1. 저장소 클론

```bash
git clone https://github.com/YOUR_GITHUB_ID/youandiknowcoffee-shorts-factory.git
cd youandiknowcoffee-shorts-factory
```

### 2. 패키지 설치

```bash
pip install -r requirements.txt
```

> macOS / Ubuntu에서 FFmpeg가 없다면:
> ```bash
> # macOS
> brew install ffmpeg
> # Ubuntu
> sudo apt-get install ffmpeg
> ```

### 3. API 키 설정

`.streamlit/secrets.toml` 파일을 생성합니다 (`.gitignore`에 포함되어 있음):

```toml
ANTHROPIC_API_KEY  = "sk-ant-..."
ELEVENLABS_API_KEY = "sk_..."
FAL_KEY            = "..."
```

### 4. 앱 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속

---

## Streamlit Community Cloud 배포

### 1. GitHub 푸시

```bash
git init
git add .
git commit -m "feat: initial commit — You and I Know Coffee Shorts Factory"
git remote add origin https://github.com/YOUR_GITHUB_ID/youandiknowcoffee-shorts-factory.git
git push -u origin main
```

### 2. Streamlit Cloud 배포

1. [share.streamlit.io](https://share.streamlit.io) 접속 → **New app**
2. GitHub 저장소 선택 → Main file: `app.py`
3. **Advanced settings > Secrets**에 아래 3개 키 등록:

```toml
ANTHROPIC_API_KEY  = "sk-ant-..."
ELEVENLABS_API_KEY = "sk_..."
FAL_KEY            = "..."
```

4. **Deploy** 클릭 → 배포 완료 후 URL 공유

---

## 앱 사용 방법

1. **새 프로젝트 시작** — 챕터명과 주제를 입력 후 "대본 생성 시작" 클릭
2. **STEP 1** — Claude AI가 12컷 대본 + Kling 프롬프트를 JSON으로 생성 (약 20~40초)
3. **STEP 2** — ElevenLabs가 전체 나레이션을 MP3로 변환
4. **STEP 3** — 컷별 영상 생성 버튼 (개별 또는 일괄). 생성 후 인라인 미리보기 가능. 마음에 안 드는 컷은 개별 재생성
5. **STEP 4** — 모든 컷 완료 후 FFmpeg·Whisper 합성 실행 → 최종 MP4 다운로드
6. **기존 프로젝트 이어하기** — 사이드바 목록에서 선택하면 중간 상태부터 재개

---

## 구현 현황

| 파일 | 상태 | 비고 |
|---|---|---|
| `app.py` | ✅ 완성 | Streamlit 메인 대시보드 |
| `src/state_manager.py` | ✅ 완성 | JSON 상태 저장·불러오기 |
| `src/prompts.py` | ✅ 완성 | Claude API 대본 생성 |
| `src/video_fal.py` | ✅ 완성 | Fal.ai Kling 영상 생성 |
| `src/audio.py` | 🔧 구현 예정 | ElevenLabs 연동 |
| `src/assembler.py` | 🔧 구현 예정 | FFmpeg·Whisper 합성 |

> `audio.py`·`assembler.py`는 ElevenLabs·Whisper 실제 API 응답 샘플 확인 후 구현 예정입니다.

---

## 생성되는 JSON 스키마 (STEP 1 결과)

```json
{
  "chapter": "CH01 커피의 탄생",
  "title": "에티오피아 예가체프의 비밀",
  "full_narration": "전체 읽을 나레이션 텍스트...",
  "scenes": [
    {
      "scene_no": 1,
      "name": "오프닝 훅",
      "narration": "대사",
      "flow_prompt": "A professional Korean barista, cinematic coffee lab, 3D cutaway view, 9:16 vertical, 4k",
      "sfx": "impact_whoosh",
      "overlay_text": "화면 자막 키워드",
      "video_url": "",
      "status": "pending"
    }
  ]
}
```

---

## 기술 스택

- **프론트엔드·서버**: [Streamlit](https://streamlit.io) ≥ 1.35
- **대본·프롬프트 AI**: [Anthropic Claude](https://anthropic.com) `claude-sonnet-4-5`
- **음성 합성 TTS**: [ElevenLabs](https://elevenlabs.io) ≥ 1.0
- **영상 생성 AI**: [Fal.ai](https://fal.ai) Kling v2.6 Pro (9:16, 5초/컷)
- **영상 편집**: [FFmpeg](https://ffmpeg.org) + [Whisper](https://github.com/openai/whisper)
- **배포**: [Streamlit Community Cloud](https://share.streamlit.io) (무료)

---

*너도나도아는커피 (You & I Know Coffee) · 블루진픽처스*
