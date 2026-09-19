"""`음성 서비스` 진입점.

ADR-0008: 오디오를 텍스트로, 텍스트를 오디오로 바꾸는 일만 한다.
대사 생성도 채점도 하지 않는다. Spring만 이 서비스를 호출한다.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import load_settings
from app.routers import health, synthesize, transcribe
from app.stt import Transcriber
from app.tts import Synthesizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """기동할 때 모델을 올리고, 종료할 때 놓아준다.

    모델 로딩을 기동 시점에 하는 이유는 두 가지다. 첫 요청만 수십 초 느려지는 것을 막고,
    /health가 200을 주는 순간이 "정말로 전사할 수 있는 순간"과 일치하게 하기 위해서다.

    **로딩이 실패해도 프로세스를 죽이지 않는다.** 죽으면 Spring이 받는 것은 연결 거부뿐이고,
    문서에 적어둔 503 `STT_NOT_READY`는 영원히 나오지 않는 죽은 계약이 된다. 서비스를 띄운 채
    /health가 503을 주게 해서, 백엔드가 "훈련 환경이 준비되지 않았다"로 거절할 근거를
    코드가 실제로 만들어 주도록 한다(슬라이스 #4).
    """
    settings = load_settings()
    transcriber = Transcriber(settings)
    synthesizer = Synthesizer(settings)

    app.state.settings = settings
    app.state.transcriber = transcriber
    app.state.synthesizer = synthesizer

    # 전사와 합성을 따로 감싼다. 하나가 실패해도 다른 하나는 올라오고, /health가
    # 어느 쪽이 준비되지 않았는지 오류 코드로 알려준다.
    try:
        transcriber.load()
    except Exception:  # noqa: BLE001 — 기동 실패를 헬스 체크로 알리고 계속 뜬다
        logger.exception(
            "전사 모델 로딩 실패 — /health가 STT_NOT_READY로 503을 준다."
            " 가중치를 내려받을 수 있는지와 compute_type이 장치에 맞는지 확인하라"
        )

    try:
        synthesizer.load()
    except Exception:  # noqa: BLE001
        logger.exception(
            "합성 모델 로딩 실패 — /health가 TTS_NOT_READY로 503을 준다."
            " 윈도에서는 mecab-ko가 설치돼 있는지 먼저 확인하라"
        )

    if transcriber.is_ready and synthesizer.is_ready:
        logger.info("음성 서비스 준비 완료 — http://%s:%d", settings.host, settings.port)

    yield

    logger.info("음성 서비스 종료")


app = FastAPI(
    title="진상 멈춰 음성 서비스",
    version="0.1.0",
    description=(
        "악성 민원 응대 훈련 서비스 「진상 멈춰」의 `음성 서비스`.\n\n"
        "한국어 음성을 텍스트로 전사하고(faster-whisper), `민원인` 대사를 음성으로"
        " 합성한다(MeloTTS). Spring 백엔드만 호출하며 외부에 노출하지 않는다(ADR-0008).\n\n"
        "주고받는 오디오는 디스크에 쓰지 않고 메모리에서만 다룬다(ADR-0006).\n\n"
        "`민원인` 대사 생성과 `태도 3축` 채점은 여기서 하지 않는다 — 그건 `추론 서비스`와"
        " 백엔드 몫이다."
    ),
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(transcribe.router)
app.include_router(synthesize.router)


def main() -> None:
    """`python -m app.main`으로 서비스를 띄운다."""
    settings = load_settings()
    # 바인딩 주소 기본값은 루프백이다. 외부에 노출하지 않는다(ADR-0008).
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
