# jinsang-stop-voice

「진상 멈춰」 `음성 서비스`(faster-whisper · MeloTTS) · `추론 서비스`(llama.cpp) 실행 설정.

- 도메인 문서 · PRD · 슬라이스: [jinsang-stop/jinsang-stop](https://github.com/jinsang-stop/jinsang-stop)
- 작업 규약: [CONTRIBUTING.md](CONTRIBUTING.md)

현재 구현된 것은 `음성 서비스`의 **한국어 전사(STT)**뿐이다. MeloTTS 합성은 #2, `추론 서비스`는 별도 이슈다.

이 서비스는 **Spring 백엔드만 호출한다**(ADR-0008). 브라우저에서 직접 부르지 않으며 외부에 노출하지 않는다.
받은 오디오는 디스크에 쓰지 않고 메모리에서만 다룬다(ADR-0006).

## 요구 사항

- Python 3.13 (확인 환경: 3.13.2 / Windows 11)
- 별도의 ffmpeg 설치는 **필요 없다.** 오디오 디코딩은 `faster-whisper`가 끌고 오는 PyAV가 처리한다.
- GPU는 선택이다. CUDA 장치가 없으면 자동으로 CPU로 떨어진다.

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate          # PowerShell은 .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

환경변수를 바꿀 일이 있으면 `.env.example`을 참고한다. 모든 값에 기본값이 있어 아무것도 설정하지 않아도 뜬다.

## 모델 내려받기

**따로 받을 필요 없다.** 처음 기동할 때 faster-whisper가 `models/`로 내려받는다(`small` 기준 약 460MB).
`models/`는 `.gitignore` 대상이라 커밋되지 않는다.

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
{ "status": "ok", "stt_model": "small", "stt_device": "cpu", "stt_compute_type": "int8" }
```

모델이 아직 안 올라왔으면 `503` · `{"error_code": "STT_NOT_READY", ...}`.

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

## 테스트

```bash
python -m pytest tests/ -v
```

라우터 계약 테스트는 모델 없이 대역으로 돈다(1초 미만).

실제 모델을 태우는 통합 검증은 기본으로 건너뛴다. 켜서 돌리려면:

```bash
JINSANGSTOP_RUN_INTEGRATION=1 python -m pytest tests/test_stt_integration.py -v
```

한국어 샘플은 윈도 내장 TTS(`ko-KR`)로 그 자리에서 합성한다. `ko-KR` 음성이 없는 기계에서는 건너뛴다.
이 검증이 이슈 #1의 완료 조건 중 "한국어 전사"와 "오디오가 디스크에 남지 않음"을 기계로 확인한다.

## 직접 확인하는 방법

루프백 밖에서 접속되지 않는지:

```bash
netstat -ano | findstr :8000        # 127.0.0.1:8000 만 LISTENING 이어야 한다
curl --max-time 5 http://<이_기계의_LAN_IP>:8000/health   # 연결 거부되어야 한다
```

요청 처리 후 오디오가 남지 않았는지 — 저장소와 `%TEMP%`에 오디오 파일이 새로 생기지 않아야 한다.
`tests/test_stt_integration.py`가 같은 것을 자동으로 확인한다.

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

`small` · CPU · `int8`, 5.46초 한국어 발화 기준 (Windows 11 / Python 3.13.2):

| 항목 | 값 |
|---|---|
| 모델 로딩 | 약 2초 (캐시), 최대 RSS 714MB |
| 정착 RSS | 약 434MB |
| 전사 | 2.3초 (실시간계수 0.42x) |

**GPU 메모리는 아직 측정하지 못했다.** 이 개발 기계에 NVIDIA GPU가 없어
`ctranslate2.get_cuda_device_count()`가 0이고 CPU로 떨어진다. 시연 장비에서 재서 이슈 #1에 남긴다.

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
