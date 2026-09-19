"""전사 API의 계약 테스트.

실제 모델을 올리지 않고 전사기를 대역(stub)으로 갈아끼워 라우터의 분기만 본다.
모델을 실제로 태우는 검증은 `tests/test_stt_integration.py`가 맡는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.deps import get_settings, get_synthesizer, get_transcriber
from app.main import app
from app.stt import AudioDecodeError, Transcriber, TranscriptionFailedError
from app.tts import Synthesizer
from tests.stubs import StubSynthesizer, StubTranscriber


def test_모델_로딩이_실패해도_서비스는_뜨고_헬스가_503을_준다(monkeypatch):
    """로딩 실패로 프로세스가 죽으면 Spring이 받는 것은 연결 거부뿐이다.

    그러면 문서에 적어둔 503 `STT_NOT_READY`는 영원히 나오지 않는 죽은 계약이 된다.
    서비스는 떠 있고 /health가 503을 주어야 백엔드가 훈련 환경 미준비로 거절할 수 있다(슬라이스 #4).
    """

    def 터지는_로딩(self):
        raise ValueError("Invalid compute type: nonsense-type")

    def 아무것도_안_하는_로딩(self):
        # 합성 모델을 실제로 올리면 테스트가 수십 초 걸린다. 여기서 보려는 것은
        # 전사 로딩이 실패해도 서비스가 뜨는지이므로 합성은 건드리지 않는다.
        return None

    monkeypatch.setattr(Transcriber, "load", 터지는_로딩)
    monkeypatch.setattr(Synthesizer, "load", 아무것도_안_하는_로딩)

    # lifespan을 실제로 태운다 — 기동이 예외로 무너지지 않아야 한다.
    with TestClient(app) as client:
        헬스 = client.get("/health")
        전사 = client.post("/transcribe", content=bytes(10))

    assert 헬스.status_code == 503
    assert 헬스.json()["error_code"] == "STT_NOT_READY"
    assert 전사.status_code == 503
    assert 전사.json()["error_code"] == "STT_NOT_READY"


@pytest.fixture(autouse=True)
def _대역_정리():
    """테스트마다 갈아끼운 의존성을 걷어낸다 — 앱 객체가 모듈 전역이라 새지 않게."""
    yield
    app.dependency_overrides.clear()


def make_client(
    transcriber: StubTranscriber,
    settings: Settings | None = None,
    synthesizer: StubSynthesizer | None = None,
) -> TestClient:
    """의존성만 대역으로 갈아끼운 테스트 클라이언트.

    **lifespan을 타지 않는다.** `with TestClient(app)`으로 열면 기동 훅이 돌아
    실제 faster-whisper 모델을 내려받고 `app.state`에 꽂은 대역을 덮어쓴다.
    그래서 컨텍스트 매니저로 열지 않고, `app.state`가 아니라 FastAPI의
    `dependency_overrides`로 꽂는다 — 기동 훅과 무관하게 라우터에 닿는다.
    """
    app.dependency_overrides[get_settings] = lambda: settings or load_settings()
    app.dependency_overrides[get_transcriber] = lambda: transcriber
    # 헬스 체크가 합성기까지 보므로 대역을 함께 꽂는다. 꽂지 않으면 app.state를 타서
    # 다른 테스트가 남긴 상태에 의존하게 된다.
    app.dependency_overrides[get_synthesizer] = lambda: synthesizer or StubSynthesizer()
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
    stub = StubTranscriber()
    client = make_client(stub)
    response = client.post("/transcribe", content=b"x" * 11)
    assert response.status_code == 413
    assert response.json()["error_code"] == "AUDIO_TOO_LARGE"
    # 전사기까지 내려가지 않았어야 한다.
    assert stub.received is None


def test_상한_초과는_Content_Length만_보고_본문_전에_끊는다(monkeypatch):
    """상한은 메모리 고갈을 막으려고 있다. 본문을 통째로 읽은 뒤 재면 그 목적을 잃는다.

    Content-Length가 상한을 넘으면 본문을 한 조각도 읽지 않고 거절해야 한다.
    """
    monkeypatch.setenv("JINSANGSTOP_MAX_AUDIO_BYTES", "10")
    client = make_client(StubTranscriber())

    읽힌_조각 = []

    def 절대_읽히면_안_되는_본문():
        # 서버가 본문을 읽으려 하면 이 제너레이터가 돌아가며 기록을 남긴다.
        읽힌_조각.append(1)
        yield b"x" * 5000

    response = client.post(
        "/transcribe",
        content=절대_읽히면_안_되는_본문(),
        headers={"content-length": "5000"},
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "AUDIO_TOO_LARGE"
    assert 읽힌_조각 == [], "Content-Length로 거절했어야 하는데 본문을 읽었다"


def test_Content_Length가_없어도_상한을_넘으면_413이다(monkeypatch):
    """청크 전송처럼 Content-Length가 없을 때도 누적 합계로 막아야 한다.

    여기서는 응답만 본다. "본문을 끝까지 읽지 않고 끊는지"는 TestClient로 확인할 수 없다 —
    httpx의 ASGI 전송이 요청 본문 제너레이터를 먼저 다 소진해 서버에 넘기기 때문에,
    서버가 중간에 멈춰도 제너레이터는 이미 끝까지 돌아 있다. 실제로 메모리가 차지 않는지는
    진짜 uvicorn 서버에 큰 본문을 보내 RSS를 재서 확인했다(README "직접 확인하는 방법").
    """
    monkeypatch.setenv("JINSANGSTOP_MAX_AUDIO_BYTES", "100")
    stub = StubTranscriber()
    client = make_client(stub)

    def 조금씩_보내는_본문():
        for _ in range(100):
            yield b"x" * 50

    response = client.post("/transcribe", content=조금씩_보내는_본문())
    assert response.status_code == 413
    assert response.json()["error_code"] == "AUDIO_TOO_LARGE"
    assert stub.received is None


def test_디코딩에_실패하면_422다():
    client = make_client(StubTranscriber(raises=AudioDecodeError("형식을 알 수 없다")))
    response = client.post("/transcribe", content=b"not audio")
    assert response.status_code == 422
    assert response.json()["error_code"] == "AUDIO_DECODE_FAILED"


def test_전사가_환경_탓으로_실패하면_422가_아니라_503이다():
    """GPU 메모리 부족을 오디오 문제로 오진하면 사용자가 같은 말을 반복하게 된다.

    ADR-0009대로 `음성 서비스`와 `추론 서비스`가 GPU를 나눠 쓰므로 현실적인 상황이다.
    백엔드가 훈련 환경 문제로 분기할 수 있도록 503과 별도 코드로 내려보낸다.
    """
    client = make_client(
        StubTranscriber(
            raises=TranscriptionFailedError("CUDA failed to allocate memory")
        )
    )
    response = client.post("/transcribe", content=bytes(100))
    assert response.status_code == 503
    assert response.json()["error_code"] == "STT_FAILED"


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

    # 503 설명에 두 오류 코드가 다 적혀 있어야 백엔드가 구분해 분기할 수 있다.
    설명_503 = 전사["responses"]["503"]["description"]
    assert "STT_NOT_READY" in 설명_503
    assert "STT_FAILED" in 설명_503

    헬스 = schema["paths"]["/health"]["get"]
    assert 헬스["summary"]
    assert {"200", "503"} <= set(헬스["responses"])
