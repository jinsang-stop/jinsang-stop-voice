"""전사 API의 계약 테스트.

실제 모델을 올리지 않고 전사기를 대역(stub)으로 갈아끼워 라우터의 분기만 본다.
모델을 실제로 태우는 검증은 `tests/test_stt_integration.py`가 맡는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.deps import get_settings, get_transcriber
from app.main import app
from app.stt import AudioDecodeError, TranscriptionResult


class StubTranscriber:
    """모델 없이 라우터를 시험하기 위한 대역."""

    def __init__(
        self, *, ready: bool = True, raises: bool = False, text: str = "안녕하세요"
    ) -> None:
        self.is_ready = ready
        self._raises = raises
        self._text = text
        self.received: bytes | None = None

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self.received = audio_bytes
        if self._raises:
            raise AudioDecodeError("형식을 알 수 없다")
        return TranscriptionResult(
            text=self._text, audio_seconds=1.5, processing_seconds=0.3
        )


@pytest.fixture(autouse=True)
def _대역_정리():
    """테스트마다 갈아끼운 의존성을 걷어낸다 — 앱 객체가 모듈 전역이라 새지 않게."""
    yield
    app.dependency_overrides.clear()


def make_client(
    transcriber: StubTranscriber, settings: Settings | None = None
) -> TestClient:
    """의존성만 대역으로 갈아끼운 테스트 클라이언트.

    **lifespan을 타지 않는다.** `with TestClient(app)`으로 열면 기동 훅이 돌아
    실제 faster-whisper 모델을 내려받고 `app.state`에 꽂은 대역을 덮어쓴다.
    그래서 컨텍스트 매니저로 열지 않고, `app.state`가 아니라 FastAPI의
    `dependency_overrides`로 꽂는다 — 기동 훅과 무관하게 라우터에 닿는다.
    """
    app.dependency_overrides[get_settings] = lambda: settings or load_settings()
    app.dependency_overrides[get_transcriber] = lambda: transcriber
    return TestClient(app)


def test_헬스는_준비됐으면_ok를_준다():
    client = make_client(StubTranscriber())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_헬스는_모델이_없으면_503을_준다():
    """세션 시작 전 헬스 확인이 실패해야 백엔드가 훈련 환경 미준비로 거절할 수 있다."""
    client = make_client(StubTranscriber(ready=False))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error_code"] == "STT_NOT_READY"


def test_전사는_텍스트와_소요시간을_준다():
    stub = StubTranscriber(text="죄송합니다 손님")
    client = make_client(stub)
    response = client.post("/transcribe", content=b"\x00\x01\x02")
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "죄송합니다 손님"
    assert body["audio_seconds"] == 1.5
    assert body["processing_seconds"] == 0.3
    assert stub.received == b"\x00\x01\x02"


def test_말소리가_없으면_오류가_아니라_빈_문자열이다():
    """`음성 서비스`는 변환만 한다. 빈 전사로 무엇을 할지는 백엔드가 정한다(슬라이스 #4)."""
    client = make_client(StubTranscriber(text=""))
    response = client.post("/transcribe", content=b"\x00\x01\x02")
    assert response.status_code == 200
    assert response.json()["text"] == ""


def test_본문이_비면_400이다():
    client = make_client(StubTranscriber())
    response = client.post("/transcribe", content=b"")
    assert response.status_code == 400
    assert response.json()["error_code"] == "EMPTY_REQUEST_BODY"


def test_오디오가_상한을_넘으면_413이다(monkeypatch):
    monkeypatch.setenv("JINSANGSTOP_MAX_AUDIO_BYTES", "10")
    client = make_client(StubTranscriber())
    response = client.post("/transcribe", content=b"x" * 11)
    assert response.status_code == 413
    assert response.json()["error_code"] == "AUDIO_TOO_LARGE"


def test_디코딩에_실패하면_422다():
    client = make_client(StubTranscriber(raises=True))
    response = client.post("/transcribe", content=b"not audio")
    assert response.status_code == 422
    assert response.json()["error_code"] == "AUDIO_DECODE_FAILED"


def test_모델이_없으면_전사는_503이다():
    client = make_client(StubTranscriber(ready=False))
    response = client.post("/transcribe", content=b"\x00")
    assert response.status_code == 503
    assert response.json()["error_code"] == "STT_NOT_READY"


def test_API_문서에_엔드포인트와_응답이_다_적혀_있다():
    """CONTRIBUTING: 엔드포인트에는 FastAPI 문서 기능을 전부 채운다."""
    client = make_client(StubTranscriber())
    schema = client.get("/openapi.json").json()

    전사 = schema["paths"]["/transcribe"]["post"]
    assert 전사["summary"]
    assert 전사["description"]
    assert 전사["tags"] == ["stt"]
    # 성공과 네 가지 실패 코드가 모두 문서에 있어야 백엔드가 분기를 읽을 수 있다.
    assert {"200", "400", "413", "422", "503"} <= set(전사["responses"])
    assert "application/octet-stream" in 전사["requestBody"]["content"]

    헬스 = schema["paths"]["/health"]["get"]
    assert 헬스["summary"]
    assert {"200", "503"} <= set(헬스["responses"])
