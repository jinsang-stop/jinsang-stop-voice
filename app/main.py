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
from app.routers import health, transcribe
from app.stt import Transcriber

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
    """
    settings = load_settings()
    transcriber = Transcriber(settings)

    app.state.settings = settings
    app.state.transcriber = transcriber

    transcriber.load()
    logger.info("음성 서비스 준비 완료 — http://%s:%d", settings.host, settings.port)

    yield

    logger.info("음성 서비스 종료")


app = FastAPI(
    title="진상 멈춰 음성 서비스",
    version="0.1.0",
    description=(
        "악성 민원 응대 훈련 서비스 「진상 멈춰」의 `음성 서비스`.\n\n"
        "한국어 음성을 텍스트로 전사한다. Spring 백엔드만 호출하며 외부에 노출하지 않는다"
        " (ADR-0008). 받은 오디오는 디스크에 쓰지 않고 메모리에서만 다룬다(ADR-0006)."
    ),
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(transcribe.router)


def main() -> None:
    """`python -m app.main`으로 서비스를 띄운다."""
    settings = load_settings()
    # 바인딩 주소 기본값은 루프백이다. 외부에 노출하지 않는다(ADR-0008).
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
