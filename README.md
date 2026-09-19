# jinsang-stop-voice

「진상 멈춰」 `음성 서비스`(faster-whisper · MeloTTS) · `추론 서비스`(llama.cpp) 실행 설정.

- 도메인 문서 · PRD · 슬라이스: [jinsang-stop/jinsang-stop](https://github.com/jinsang-stop/jinsang-stop)
- 작업 규약: [CONTRIBUTING.md](CONTRIBUTING.md)

이 저장소에는 두 가지가 들어 있다.

- **`음성 서비스`** — faster-whisper 전사와 MeloTTS 합성을 하는 파이썬 HTTP 서비스
- **`추론 서비스` 실행 설정** — llama.cpp `llama-server`를 ADR-0009 기준값으로 띄우는 스크립트

`민원인` 대사 생성과 `태도 3축` 채점은 여기서 하지 않는다. `추론 서비스`는 받은 요청을 그대로
추론할 뿐이고, 프롬프트 조립과 `출력 검사`는 백엔드 몫이다.

이 서비스는 **Spring 백엔드만 호출한다**(ADR-0008). 브라우저에서 직접 부르지 않으며 외부에 노출하지 않는다.
받은 오디오는 디스크에 쓰지 않고 메모리에서만 다룬다(ADR-0006).

## 요구 사항

- Python 3.13 (확인 환경: 3.13.2 / Windows 11)
- 별도의 ffmpeg 설치는 **필요 없다.** 오디오 디코딩은 `faster-whisper`가 끌고 오는 PyAV가 처리한다.
- C++ 빌드 도구도 **필요 없다.** 아래 설치 절차대로 하면 전부 미리 빌드된 휠로 깔린다.
- 전사는 GPU가 있으면 쓰고 없으면 CPU로 떨어진다. **합성은 언제나 CPU다**(ADR-0009) —
  시연 장비의 VRAM 8GB는 전사와 `추론 서비스`가 나눠 쓴다.

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate          # PowerShell은 .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install --no-deps git+https://github.com/myshell-ai/MeloTTS.git
```

**마지막 줄의 `--no-deps`는 실수가 아니다.** MeloTTS 0.1.2의 `setup.py`는 `numpy==1.26.4`와
`transformers==4.27.4`처럼 오래된 버전을 못박아 두었는데, 그 조합은 Python 3.13용 휠이 없어
소스 빌드로 떨어지고(빌드 도구가 필요해진다) 전사가 쓰는 numpy 2.x도 함께 끌어내린다.
그래서 코드만 받고, 실제로 import 되는 것들은 `requirements.txt`에 최신 버전으로 고정해 두었다.
확인한 조합에서 MeloTTS는 `transformers 5.17.0` · `numpy 2.5.3`과 문제없이 돈다.

환경변수를 바꿀 일이 있으면 `.env.example`을 참고한다. 모든 값에 기본값이 있어 아무것도 설정하지 않아도 뜬다.

### 한국어 발음 처리에 관하여

MeloTTS의 한국어 경로는 `g2pkk`로 한글을 발음대로 바꾸고, 그 과정에서 형태소 분석기를 쓴다.
`g2pkk`는 윈도에서 **`eunjeon`만** 찾는데, `eunjeon`은 PyPI에 Python 3.6용 윈도 휠까지만 올라와 있어
3.13에서는 소스 빌드가 유일하고 그러려면 Visual Studio C++ 빌드 도구가 필요하다.

시연 장비에 빌드 도구를 얹지 않으려고, 같은 mecab-ko 사전을 쓰면서 3.13 윈도 휠이 있는
`mecab-ko`로 갈아끼웠다(`app/korean_g2p.py`). **발음이 달라지지 않는지 확인했다** —
`g2pkk`가 스스로 docstring에 적어둔 예시를 그대로 재현하며, `tests/test_korean_g2p.py`가 이를 지킨다.

```
나의 친구가 mp3 file 3개를 다운받고 있다  ->  나의 친구가 엠피쓰리 파일 세개를 다운받꼬 읻따
```

## 모델 내려받기

**따로 받을 필요 없다.** 처음 기동할 때 faster-whisper가 `models/`로 내려받고(`small` 기준 약 460MB),
MeloTTS도 한국어 가중치를 같은 방식으로 받는다. `models/`는 `.gitignore` 대상이라 커밋되지 않는다.

(`추론 서비스`가 쓰는 GGUF는 이것과 별개다. 아래 "추론 서비스" 절을 보라.)

한 번 받아두면 그다음부터는 캐시에서 올라온다. 네트워크가 없는 시연 환경에서는 `HF_HUB_OFFLINE=1`을
주면 허브에 접속하지 않고 캐시만 쓴다(확인함).

## 실행

```bash
python -m app.main
```

기동 로그에 `음성 서비스 준비 완료`가 찍히면 받을 준비가 된 것이다. 모델 로딩이 끝난 뒤에야
`/health`가 200을 주므로, Spring은 이것만 보고 `훈련 세션` 시작 여부를 정할 수 있다.

**모델 로딩이 실패해도 서비스는 죽지 않는다.** 로그에 `모델 로딩 실패`를 남기고 계속 떠서
`/health`가 503 `STT_NOT_READY`를 준다. 프로세스가 죽으면 Spring이 받는 것은 연결 거부뿐이고
문서에 적힌 503은 영원히 나오지 않는 죽은 계약이 되기 때문이다.

기본 주소는 `http://127.0.0.1:8000`이다. **루프백을 벗어나게 바꾸지 않는다** — 그건 배포 설정이 아니라
ADR-0008을 어기는 일이다.

API 문서: <http://127.0.0.1:8000/docs>

## 엔드포인트

### `GET /health` — 준비 여부

Spring이 `훈련 세션`을 시작하기 전에 확인한다. 200이 아니면 세션을 만들지 않는다.

```bash
curl http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "stt_model": "small", "stt_device": "cpu", "stt_compute_type": "int8",
  "tts_language": "KR", "tts_device": "cpu", "tts_sample_rate": 44100
}
```

**전사와 합성이 둘 다 올라왔을 때만 200이다.** 전사만 되고 합성이 안 되면 `민원인`이 말을
못 하므로 온전한 `훈련 세션`이 아니다. 준비되지 않은 쪽에 따라 `503` ·
`STT_NOT_READY` 또는 `TTS_NOT_READY`를 준다.

`추론 서비스`는 별도 프로세스이므로 여기서 확인하지 않는다 — 백엔드가 8081을 따로 본다.

### `POST /transcribe` — 한국어 전사

오디오를 **요청 본문에 원시 바이너리로** 담아 보낸다. multipart가 아니다 — Starlette이 1MB 넘는
업로드를 임시 파일로 디스크에 흘리기 때문에, ADR-0006을 지키려면 본문으로 받는 쪽이어야 한다.

| 항목 | 값 |
|---|---|
| 메서드 · 경로 | `POST /transcribe` |
| `Content-Type` | 오디오 형식을 적는다. 서비스가 파싱하지 않고 PyAV가 판별한다 |
| 본문 | 오디오 바이트 그대로 |

```bash
curl -X POST http://127.0.0.1:8000/transcribe \
  -H "Content-Type: audio/webm;codecs=opus" \
  --data-binary @녹음.webm
```

```json
{ "text": "죄송합니다. 손님. 규정상 그건 어렵습니다.", "audio_seconds": 5.46, "processing_seconds": 2.23 }
```

받는 형식은 `wav` · `webm/opus` · `ogg/opus` · `mp3`를 실제로 확인했다. 브라우저 `MediaRecorder`가
내보내는 `webm/opus`가 여기 포함된다.

**말소리가 없으면 오류가 아니라 빈 문자열(`text: ""`)에 200이다.** 이 서비스는 변환만 하고 판단하지
않는다 — 빈 전사에 `발화 턴`을 소모하지 않는 처리는 백엔드 몫이다(슬라이스 #4).

| 상태 | `error_code` | 언제 |
|---|---|---|
| 400 | `EMPTY_REQUEST_BODY` | 본문이 비었다 |
| 413 | `AUDIO_TOO_LARGE` | `JINSANGSTOP_MAX_AUDIO_BYTES`(기본 25MB)를 넘었다 |
| 422 | `AUDIO_DECODE_FAILED` | 보낸 바이트를 오디오로 열지 못했다 — **보낸 쪽 문제** |
| 503 | `STT_NOT_READY` | 모델이 아직 안 올라왔다 — **이쪽 문제** |
| 503 | `STT_FAILED` | 오디오는 받았는데 전사가 실패했다(예: GPU 메모리 부족) — **이쪽 문제** |

422와 503을 가르는 기준은 "누구 탓인가"다. 422는 다시 말하게 해서 풀리는 문제이고,
503 두 가지는 다시 말해도 풀리지 않는다 — 백엔드는 이 둘을 훈련 환경 문제로 다뤄야 한다.
전사 중 GPU 메모리가 부족한 경우가 `STT_FAILED`로 오는데, 이걸 422로 내려보내면 백엔드가
"다시 말해 달라"를 띄우고 사용자는 같은 말을 반복하는데 원인은 GPU에 있게 된다.

413은 `Content-Length`를 먼저 보고 본문을 받기 전에 거절한다. 헤더가 없는 청크 전송이면
받으면서 누적 합계로 세다가 상한을 넘는 순간 끊는다. 본문을 통째로 읽은 뒤 크기를 재면
상한이 막으려던 메모리 고갈을 못 막기 때문이다.

### `POST /synthesize` — 한국어 합성

`민원인` 대사를 음성으로 바꾼다. **성공 응답의 본문은 JSON이 아니라 오디오 바이트**다.

| 항목 | 값 |
|---|---|
| 메서드 · 경로 | `POST /synthesize` |
| `Content-Type` | `application/json` |
| 바디 | `{"text": "...", "speed": 1.0}` — `speed`는 생략 가능 |
| 응답 | `audio/wav` (16비트 PCM, 모노, 44100Hz) |

```bash
curl -X POST http://127.0.0.1:8000/synthesize \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"환불은 영수증이 있어야 가능합니다.\"}" \
  --output 민원인.wav
```

본문이 오디오라 측정값을 JSON에 섞을 수 없으므로 헤더로 준다.

```
content-type: audio/wav
x-audio-seconds: 3.52
x-processing-seconds: 2.80
x-sample-rate: 44100
```

`speed`를 생략하면 `JINSANGSTOP_TTS_SPEED`(기본 1.0)를 쓴다. MeloTTS가 노출하는 조절 값은
`speed`와 `speaker_id`뿐이므로 `민원인`의 분노 어조는 음성이 아니라 대사 자체로 표현한다(ADR-0008).

이 서비스는 대사를 만들지도 검사하지도 않는다. 금칙 표현과 한국어 여부를 보는 `출력 검사`는
백엔드 몫이고(ADR-0009), 여기 도착한 텍스트는 이미 통과한 것으로 본다.

| 상태 | `error_code` | 언제 |
|---|---|---|
| 400 | `EMPTY_TEXT` | 텍스트가 비었거나 공백뿐이다 |
| 413 | `TEXT_TOO_LONG` | `JINSANGSTOP_MAX_TEXT_CHARS`(기본 500자)를 넘었다 |
| 503 | `TTS_NOT_READY` | 모델이 아직 안 올라왔다 — **이쪽 문제** |
| 503 | `TTS_FAILED` | 텍스트는 받았는데 합성이 실패했다 — **이쪽 문제** |

합성 실패에 422를 두지 않은 것은 의도적이다. 보낸 텍스트가 잘못된 경우와 이쪽 장애를
신뢰할 만하게 가려낼 방법이 없어서, 가려낼 수 있는 척하는 대신 전부 이쪽 문제로 보고한다.
길이와 빈 문자열처럼 확실히 판별되는 것만 먼저 거른다.

## 추론 서비스 (llama-server)

`민원인` 대사 생성과 `태도 3축` 채점을 맡는 로컬 LLM 서비스다. `음성 서비스`와 **별개 프로세스**이고,
이 저장소는 실행 설정만 갖는다. 프롬프트 조립과 `출력 검사`는 백엔드 몫이다(ADR-0009).

### 내려받기

둘 다 `.gitignore` 대상이라 커밋되지 않는다.

1. **llama-server** — [ggml-org/llama.cpp 릴리스](https://github.com/ggml-org/llama.cpp/releases)에서
   빌드를 받아 `tools/llama-<빌드번호>/`에 푼다.
   - 시연 장비(RTX 5060 Ti)는 **CUDA 빌드**를 쓴다: `llama-<빌드>-bin-win-cuda-13.4-x64.zip`.
     CUDA 툴킷이 설치돼 있지 않으면 같은 릴리스의 `cudart-llama-bin-win-cuda-13.4-x64.zip`도 함께 푼다.
   - Vulkan 백엔드는 쓰지 않는다(ADR-0009).
2. **모델 가중치** — Qwen3.6-35B-A3B의 GGUF를 `models/`에 둔다. 공식 가중치에서 양자화한 것만 쓰고,
   검열이 제거된(abliterated·uncensored) 변형은 쓰지 않는다(ADR-0009).
   Q4_K_M이 약 21GB이므로 디스크와 RAM 여유를 먼저 확인한다.

### 실행

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-inference-service.ps1
```

경로와 인자는 환경변수로 바꾼다(`.env.example`의 "추론 서비스" 절). 기본값은 ADR-0009의
실행 기준값 그대로다. 배치 파일이 아니라 PowerShell인 이유는, cmd가 UTF-8로 저장한 한글 주석을
콘솔 코드페이지로 잘못 읽어 스크립트 자체가 깨지기 때문이다.

### 확인된 지원 범위

ADR-0009와 PRD-v2가 "받은 `llama-server` 버전에서 확인한다"고 남겨 둔 항목들이다.
**빌드 `b11026`(`0.4.1-dev`, 커밋 `b49650adb`)에서 직접 확인했다.**

시연 장비가 없어 CUDA 빌드 대신 같은 릴리스의 **CPU 빌드**에 Qwen3-0.6B를 올려 확인했다.
여기서 보는 것은 API가 그 인자를 받아들이는지이고 그건 백엔드 종류가 아니라 버전의 함수이므로,
시연 장비에서는 **같은 태그의 CUDA 빌드**를 쓰면 같은 결과가 나온다.

| 항목 | 결과 | 확인 방법 |
|---|---|---|
| `id_slot` | **된다** | `/completion` 응답에 `id_slot: 1`이 그대로 돌아오고, 서버 로그에 `selected slot by id (1)`이 찍힌다 |
| `chat_template_kwargs` | **된다** | `{"enable_thinking": false}`를 주면 `reasoning_content`가 사라진다. 빼면 다시 나타난다 |
| JSON 스키마 응답 형식 | **된다** | `response_format: json_schema`에 한글 속성명(`대사`·`진정함`)과 `strict: true`를 주었더니 스키마대로 파싱되는 JSON만 나왔다 |
| 슬롯당 컨텍스트 | `-c` ÷ `-np` | `-c 16384 -np 2`로 띄우면 `n_ctx_slot = 8192`다. 슬롯당 값을 직접 주려면 `--kv-unified-per-slot`이 따로 있다 |

주의할 점 두 가지를 함께 확인했다.

- **`id_slot` 범위를 검사하지 않는다.** 슬롯이 2개인데 `id_slot: 99`를 보내도 오류가 아니라
  200이 돌아오고 로그에는 `selected slot by id (99)`가 찍히지만 실제로는 다른 슬롯이 쓰인다.
  "슬롯 0은 연기, 슬롯 1은 채점"이라는 경계(ADR-0009)를 서버가 지켜 주지 않으므로 백엔드가
  보내는 값을 스스로 맞춰야 한다.
- **CORS 기본값이 `*`다.** llama-server가 기동할 때 스스로 위험하다고 경고한다. 루프백 바인딩이
  외부는 막지만 시연 장비 브라우저에서 열린 아무 페이지나 요청을 보낼 수 있으므로, 실행 스크립트에
  `--cors-origins localhost`를 넣어 좁혀 두었다. Spring은 서버에서 부르므로 `Origin`이 없어 영향이 없다.

추론 모드는 요청마다 `chat_template_kwargs`로 끄는 것 외에 서버 인자 `--reasoning off`로도 끌 수 있다.
어느 쪽을 쓸지는 백엔드와 맞춘다.

## 테스트

```bash
python -m pytest tests/ -v
```

라우터 계약 테스트와 한국어 발음 테스트는 모델 없이 돈다(몇 초).

실제 모델을 태우는 통합 검증은 기본으로 건너뛴다. 켜서 돌리려면:

```bash
JINSANGSTOP_RUN_INTEGRATION=1 python -m pytest tests/ -v
```

- `tests/test_stt_integration.py` — 한국어 전사. 샘플은 윈도 내장 TTS(`ko-KR`)로 그 자리에서
  합성하고 바이트를 읽는 즉시 지운다. `ko-KR` 음성이 없는 기계에서는 건너뛴다.
- `tests/test_tts_integration.py` — 한국어 합성. **파형이 있다는 것만으로 "재생 가능"을
  주장하지 않는다** — 합성한 음성을 이 서비스의 전사기로 되돌려 알아들을 수 있는 한국어인지까지 본다.
- `tests/test_korean_g2p.py` — 형태소 분석기를 갈아끼운 뒤에도 발음이 같은지. 모델이 필요 없어 항상 돈다.

이 검증들이 이슈 #1·#2의 완료 조건 중 "한국어 전사", "재생 가능한 음성", "오디오가 디스크에
남지 않음"을 기계로 확인한다.

## 직접 확인하는 방법

루프백 밖에서 접속되지 않는지:

```bash
netstat -ano | findstr :8000        # 127.0.0.1:8000 만 LISTENING 이어야 한다
curl --max-time 5 http://<이_기계의_LAN_IP>:8000/health   # 연결 거부되어야 한다
```

요청 처리 후 오디오가 남지 않았는지 — 저장소와 `%TEMP%`에 오디오 파일이 새로 생기지 않아야 한다.
`tests/test_stt_integration.py`가 같은 것을 자동으로 확인한다.

합성이 실제로 알아들을 수 있는 한국어인지 — 합성한 WAV를 그대로 전사에 넣어 본다.
서비스를 띄운 채로:

```bash
curl -X POST http://127.0.0.1:8000/synthesize -H "Content-Type: application/json" \
  -d "{\"text\": \"죄송합니다 손님. 규정상 그건 어렵습니다.\"}" --output 확인.wav
curl -X POST http://127.0.0.1:8000/transcribe -H "Content-Type: audio/wav" --data-binary @확인.wav
```

확인한 결과는 `{"text":"죄송합니다, 손님. 뷰정상 그건 어렵습니다.", ...}`였다.
작은 전사 모델이 합성음을 다루므로 토씨까지 같지는 않지만, 알아들을 수 있는 한국어가 나온다는
증거로는 충분하다. `tests/test_tts_integration.py`가 같은 것을 자동으로 확인한다.
(확인이 끝나면 `확인.wav`를 지운다 — 서비스는 파일을 만들지 않지만 이 명령은 만든다.)

크기 상한이 메모리를 정말 지키는지 — 상한을 작게 두고 큰 본문을 보내면서 프로세스 RSS를 본다.
거절되는 동안 RSS가 올라가지 않아야 한다. 이 확인은 테스트로 옮기지 못했다.
`TestClient`(httpx의 ASGI 전송)가 요청 본문을 서버에 넘기기 전에 다 소진해서, 서버가 중간에
끊어도 클라이언트 쪽에서는 구분이 되지 않기 때문이다.

```bash
JINSANGSTOP_MAX_AUDIO_BYTES=1024 JINSANGSTOP_VOICE_PORT=8020 python -m app.main
# 다른 셸에서 — 300MB를 보내고 RSS를 지켜본다
curl -X POST http://127.0.0.1:8020/transcribe --data-binary @big.bin -w "%{size_upload}"
```

확인한 결과는 `Content-Length`가 있으면 업로드 0바이트에 RSS 증가 0MB,
청크 전송이면 300MB 중 약 0.6MB만 올라가고(소켓 버퍼에 실려 있던 분량) RSS 증가 0MB다.

## 측정값 (참고)

**이 값들은 시연 장비의 것이 아니다.** 측정한 기계는 Intel Core Ultra 5 125H · RAM 16GB ·
NVIDIA GPU 없음(Intel Arc 내장)이고, ADR-0009가 말하는 시연 장비는 RTX 5060 Ti · RAM 64GB ·
Core Ultra 7이다. 전사는 GPU가 없어 CPU `int8`로 떨어졌고, 합성은 어차피 CPU다.

전사 — `small` · CPU · `int8`, 5.46초 한국어 발화:

| 항목 | 값 |
|---|---|
| 모델 로딩 | 약 2초 (캐시), 최대 RSS 714MB |
| 전사 | 2.3초 (실시간계수 0.42x) |

합성 — MeloTTS `KR` · CPU, 예열 뒤 3회 평균:

| 항목 | 값 |
|---|---|
| 첫 기동(전사+합성 로딩, 예열 포함) | 약 10초 |
| 합성 | 오디오 1초당 약 0.77초 (실시간계수 0.74~0.80x) |
| 출력 | 16비트 PCM · 모노 · 44100Hz |

`JINSANGSTOP_TTS_WARMUP=false`로 예열을 끄면 **첫 합성만** 실시간계수 2.8배까지 느려진다.
기본값을 켜 둔 이유다 — 첫 `발화 턴`만 유독 느린 것은 훈련 흐름을 끊는다.

전사와 합성 모델을 모두 올린 프로세스의 RSS는 약 2.35GB다. ADR-0009 자원 배치표에서
MeloTTS는 CPU 칸에 있으므로 이 값은 VRAM이 아니라 RAM을 쓴다.

**GPU 메모리는 아직 측정하지 못했다.** 이슈 #1·#2의 GPU 관련 완료 조건은 비워 두었다.
전사 모델과 `추론 서비스`를 함께 올린 실측값은 시연 장비에서 재서 이슈에 댓글로 남긴다.

## 설정

전부 환경변수이고 전부 기본값이 있다. 자세한 설명은 [.env.example](.env.example)에 있다.

| 변수 | 기본값 |
|---|---|
| `JINSANGSTOP_VOICE_HOST` | `127.0.0.1` |
| `JINSANGSTOP_VOICE_PORT` | `8000` |
| `JINSANGSTOP_STT_MODEL` | `small` |
| `JINSANGSTOP_STT_DEVICE` | `auto` (CUDA 있으면 `cuda`, 없으면 `cpu`) |
| `JINSANGSTOP_STT_COMPUTE_TYPE` | `cuda`면 `float16`, `cpu`면 `int8` |
| `JINSANGSTOP_STT_BEAM_SIZE` | `5` |
| `JINSANGSTOP_STT_DOWNLOAD_ROOT` | `./models` |
| `JINSANGSTOP_MAX_AUDIO_BYTES` | `26214400` (25MB) |
| `JINSANGSTOP_TTS_WARMUP` | `true` |
| `JINSANGSTOP_TTS_SPEED` | `1.0` |
| `JINSANGSTOP_MAX_TEXT_CHARS` | `500` |

`추론 서비스`는 이 서비스가 읽지 않는 별도 환경변수를 쓴다(`JINSANGSTOP_LLAMA_*`).
목록은 [.env.example](.env.example)에 있고, 실행 스크립트만 그 값을 본다.
