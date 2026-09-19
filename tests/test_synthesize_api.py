"""합성 API의 계약 테스트.

실제 MeloTTS를 올리지 않고 합성기를 대역으로 갈아끼워 라우터의 분기만 본다.
모델을 실제로 태우는 검증은 `tests/test_tts_integration.py`가 맡는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.deps import get_settings, get_synthesizer, get_transcriber
from app.main import app
from app.tts import SynthesisFailedError
from tests.stubs import StubSynthesizer, StubTranscriber


@pytest.fixture(autouse=True)
def _대역_정리():
    """테스트마다 갈아끼운 의존성을 걷어낸다 — 앱 객체가 모듈 전역이라 새지 않게."""
    yield
    app.dependency_overrides.clear()


def make_client(
    synthesizer: StubSynthesizer, settings: Settings | None = None
) -> TestClient:
    """의존성만 대역으로 갈아끼운 테스트 클라이언트.

    **lifespan을 타지 않는다.** 열면 기동 훅이 돌아 실제 모델을 내려받는다.
    """
    app.dependency_overrides[get_settings] = lambda: settings or load_settings()
    app.dependency_overrides[get_synthesizer] = lambda: synthesizer
    app.dependency_overrides[get_transcriber] = lambda: StubTranscriber()
    return TestClient(app)


def test_합성은_WAV_오디오를_돌려준다():
    """TTS 계약: 텍스트 → 오디오. 본문은 JSON이 아니라 오디오 바이트다(슬라이스 #5)."""
    대역 = StubSynthesizer()
    client = make_client(대역)
    response = client.post("/synthesize", json={"text": "환불은 어렵습니다."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    # RIFF/WAVE 머리표가 붙은 진짜 WAV여야 재생할 수 있다.
    assert response.content[:4] == b"RIFF"
    assert response.content[8:12] == b"WAVE"
    assert 대역.received_text == "환불은 어렵습니다."


def test_합성은_길이와_소요시간을_헤더로_준다():
    """본문이 오디오라 JSON을 섞을 수 없으므로 측정값은 헤더로 준다."""
    client = make_client(StubSynthesizer())
    response = client.post("/synthesize", json={"text": "안녕하세요."})

    assert response.status_code == 200
    assert response.headers["x-audio-seconds"] == "2.50"
    assert response.headers["x-processing-seconds"] == "1.10"
    assert response.headers["x-sample-rate"] == "44100"


def test_speed를_생략하면_설정값을_쓴다(monkeypatch):
    monkeypatch.setenv("JINSANGSTOP_TTS_SPEED", "1.3")
    대역 = StubSynthesizer()
    client = make_client(대역)
    response = client.post("/synthesize", json={"text": "안녕하세요."})

    assert response.status_code == 200
    assert 대역.received_speed == pytest.approx(1.3)


def test_speed를_주면_그것을_쓴다():
    대역 = StubSynthesizer()
    client = make_client(대역)
    response = client.post("/synthesize", json={"text": "안녕하세요.", "speed": 0.8})

    assert response.status_code == 200
    assert 대역.received_speed == pytest.approx(0.8)


def test_텍스트가_비면_400이다():
    대역 = StubSynthesizer()
    client = make_client(대역)
    response = client.post("/synthesize", json={"text": ""})

    assert response.status_code == 400
    assert response.json()["error_code"] == "EMPTY_TEXT"
    assert 대역.received_text is None


def test_공백뿐인_텍스트도_400이다():
    """합성기까지 내려보내면 빈 오디오가 나온다. 라우터가 먼저 걸러야 한다."""
    대역 = StubSynthesizer()
    client = make_client(대역)
    response = client.post("/synthesize", json={"text": "   \n  "})

    assert response.status_code == 400
    assert response.json()["error_code"] == "EMPTY_TEXT"
    assert 대역.received_text is None


def test_텍스트가_상한을_넘으면_413이다(monkeypatch):
    monkeypatch.setenv("JINSANGSTOP_MAX_TEXT_CHARS", "10")
    대역 = StubSynthesizer()
    client = make_client(대역)
    response = client.post("/synthesize", json={"text": "가" * 11})

    assert response.status_code == 413
    assert response.json()["error_code"] == "TEXT_TOO_LONG"
    assert 대역.received_text is None


def test_합성이_실패하면_503이다():
    """합성 실패를 422로 내려보내면 백엔드가 대사 탓으로 오진한다.

    `출력 검사`를 통과한 대사가 도착하므로(ADR-0009) 실패는 이쪽 환경 문제다.
    """
    client = make_client(StubSynthesizer(raises=SynthesisFailedError("모델이 죽었다")))
    response = client.post("/synthesize", json={"text": "안녕하세요."})

    assert response.status_code == 503
    assert response.json()["error_code"] == "TTS_FAILED"


def test_모델이_없으면_503이다():
    대역 = StubSynthesizer(ready=False)
    client = make_client(대역)
    response = client.post("/synthesize", json={"text": "안녕하세요."})

    assert response.status_code == 503
    assert response.json()["error_code"] == "TTS_NOT_READY"
    assert 대역.received_text is None


def test_헬스는_합성이_준비되지_않으면_503이다():
    """전사만 되고 합성이 안 되면 `민원인`이 말을 못 한다. 온전한 세션이 아니다."""
    client = make_client(StubSynthesizer(ready=False))
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["error_code"] == "TTS_NOT_READY"


def test_헬스는_둘_다_준비되면_합성_정보까지_준다():
    client = make_client(StubSynthesizer())
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tts_language"] == "KR"
    # ADR-0009: TTS는 CPU다. GPU는 전사와 `추론 서비스` 몫이다.
    assert body["tts_device"] == "cpu"
    assert body["tts_sample_rate"] == 44100


def test_API_문서에_합성_엔드포인트가_다_적혀_있다():
    """CONTRIBUTING: 엔드포인트에는 FastAPI 문서 기능을 전부 채운다."""
    client = make_client(StubSynthesizer())
    schema = client.get("/openapi.json").json()

    합성 = schema["paths"]["/synthesize"]["post"]
    assert 합성["summary"]
    assert 합성["description"]
    assert 합성["tags"] == ["tts"]
    assert {"200", "400", "413", "503"} <= set(합성["responses"])
    # 성공 응답이 오디오임이 문서에 드러나야 백엔드가 JSON으로 파싱하지 않는다.
    assert "audio/wav" in 합성["responses"]["200"]["content"]

    설명_503 = 합성["responses"]["503"]["description"]
    assert "TTS_NOT_READY" in 설명_503
    assert "TTS_FAILED" in 설명_503
