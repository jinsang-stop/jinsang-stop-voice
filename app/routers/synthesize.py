"""합성 엔드포인트.

`민원인` 대사를 WAV 오디오로 돌려준다. 성공 응답의 본문은 JSON이 아니라 **오디오 바이트**다.
합성한 오디오를 디스크에 쓰지 않고 메모리에서 바로 응답에 싣는다(ADR-0006).

이 서비스는 대사를 만들지도 검사하지도 않는다. 금칙 표현과 한국어 여부를 보는 `출력 검사`는
백엔드 몫이고(ADR-0009), 여기 도착한 텍스트는 이미 통과한 것으로 본다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.config import Settings
from app.deps import get_settings, get_synthesizer
from app.schemas import ErrorResponse, SynthesisRequest
from app.tts import SynthesisFailedError, Synthesizer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tts"])


def _error(status_code: int, error_code: str, message: str) -> JSONResponse:
    """오류 응답을 한 형태로 만든다."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error_code=error_code, message=message).model_dump(),
    )


@router.post(
    "/synthesize",
    summary="한국어 텍스트를 음성으로 합성",
    description=(
        "`민원인` 대사를 16비트 PCM WAV로 합성해 **오디오 바이트를 그대로** 돌려준다."
        " 성공 응답의 `Content-Type`은 `audio/wav`이고, 실패 응답만 JSON이다.\n\n"
        "합성한 오디오는 디스크에 쓰지 않는다(ADR-0006). 재생 후 보관하지 않는 것은 호출한"
        " 쪽의 몫이다.\n\n"
        "ADR-0009에 따라 CPU로 합성한다. 시연 장비의 VRAM은 전사와 `추론 서비스`가 나눠 쓴다."
    ),
    response_class=Response,
    response_description="합성된 WAV 오디오",
    responses={
        status.HTTP_200_OK: {
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
            "description": "합성된 WAV 오디오. 헤더의 X-Audio-Seconds로 길이를 알 수 있다",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "텍스트가 비었거나 공백뿐이다",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "텍스트가 허용 길이를 넘었다",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": (
                "모델이 아직 올라오지 않았거나(`TTS_NOT_READY`),"
                " 텍스트는 받았는데 합성이 실패했다(`TTS_FAILED`)."
                " 둘 다 이쪽 환경 문제이므로 백엔드는 훈련 환경 미준비로 다룬다"
            ),
        },
    },
)
async def synthesize(
    요청: SynthesisRequest,
    settings: Settings = Depends(get_settings),
    synthesizer: Synthesizer = Depends(get_synthesizer),
):
    """텍스트를 한국어 음성으로 합성한다."""
    if not synthesizer.is_ready:
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TTS_NOT_READY",
            "MeloTTS 모델이 아직 로딩되지 않았다.",
        )

    text = 요청.text.strip()
    if not text:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "EMPTY_TEXT",
            "합성할 텍스트가 없다.",
        )

    if len(text) > settings.max_text_chars:
        return _error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "TEXT_TOO_LONG",
            f"텍스트가 {len(text)}자로 상한 {settings.max_text_chars}자를 넘었다.",
        )

    speed = 요청.speed if 요청.speed is not None else settings.tts_speed

    try:
        # 합성은 CPU를 오래 붙잡으므로 이벤트 루프를 막지 않도록 스레드로 넘긴다.
        # 그래야 합성 중에도 /health가 응답한다.
        결과 = await run_in_threadpool(synthesizer.synthesize, text, speed)
    except SynthesisFailedError as exc:
        # 텍스트 탓으로 돌리지 않는다. 가려낼 수 없는 것을 가려낸 척하지 않는다.
        logger.error("합성 실패 — 환경 문제다: %s", exc)
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TTS_FAILED",
            f"텍스트는 받았지만 합성에 실패했다: {exc}",
        )

    logger.info(
        "합성 완료 — 글자 %d자, 오디오 %.2f초, 처리 %.2f초",
        len(text),
        결과.audio_seconds,
        결과.processing_seconds,
    )

    # 길이와 소요 시간은 헤더로 준다. 본문이 오디오라 JSON을 섞을 수 없다.
    return Response(
        content=결과.wav,
        media_type="audio/wav",
        headers={
            "X-Audio-Seconds": f"{결과.audio_seconds:.2f}",
            "X-Processing-Seconds": f"{결과.processing_seconds:.2f}",
            "X-Sample-Rate": str(결과.sample_rate),
        },
    )
