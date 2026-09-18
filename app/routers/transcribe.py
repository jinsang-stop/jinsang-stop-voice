"""전사 엔드포인트.

오디오를 **원시 바이너리 본문**으로 받는다. multipart(`UploadFile`)를 쓰지 않은 이유는
Starlette이 1MB를 넘는 업로드를 임시 파일로 디스크에 흘리기 때문이다.
ADR-0006은 사용자 음성을 보관하지 않기로 했고, 지웠다가 마는 것보다
애초에 디스크에 쓰지 않는 쪽이 그 약속을 코드로 지키는 방법이다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.config import Settings
from app.deps import get_settings, get_transcriber
from app.schemas import ErrorResponse, TranscriptionResponse
from app.stt import AudioDecodeError, Transcriber, TranscriptionFailedError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stt"])


def _error(status_code: int, error_code: str, message: str) -> JSONResponse:
    """오류 응답을 한 형태로 만든다."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error_code=error_code, message=message).model_dump(),
    )


@router.post(
    "/transcribe",
    summary="한국어 음성을 텍스트로 전사",
    description=(
        "오디오 바이트를 요청 본문에 그대로 담아 보낸다. `Content-Type`은 오디오 형식을 적되"
        " 서비스가 형식을 직접 파싱하지 않고 PyAV가 판별하므로 webm/ogg/wav/mp3 모두 받는다.\n\n"
        "**말소리가 없으면 오류가 아니라 빈 문자열(`text: \"\"`)을 돌려준다.** 이 서비스는 변환만 하고"
        " 판단하지 않는다 — 빈 전사에 `발화 턴`을 소모하지 않는 처리는 백엔드 몫이다(슬라이스 #4).\n\n"
        "받은 오디오는 메모리에서만 다루고 디스크에 쓰지 않는다(ADR-0006)."
    ),
    response_model=TranscriptionResponse,
    response_description="전사된 텍스트와 소요 시간",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "본문이 비어 있다",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "오디오가 허용 크기를 넘었다",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "오디오로 디코딩하지 못했다",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": (
                "모델이 아직 올라오지 않았거나(`STT_NOT_READY`),"
                " 오디오는 멀쩡한데 전사가 실패했다(`STT_FAILED`)."
                " 둘 다 이쪽 환경 문제이므로 백엔드는 훈련 환경 미준비로 다룬다"
            ),
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def transcribe(
    request: Request,
    settings: Settings = Depends(get_settings),
    transcriber: Transcriber = Depends(get_transcriber),
):
    """요청 본문의 오디오를 한국어로 전사한다."""
    if not transcriber.is_ready:
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STT_NOT_READY",
            "faster-whisper 모델이 아직 로딩되지 않았다.",
        )

    # 상한을 **본문을 다 받기 전에** 적용한다. `await request.body()`로 통째로 읽은 뒤
    # 길이를 재면 이미 메모리에 올라온 다음이라, 상한이 막으려던 메모리 고갈을 못 막는다.
    # 먼저 Content-Length를 보고, 없거나 못 믿을 때는 받으면서 누적 합계로 끊는다.
    선언된_크기 = request.headers.get("content-length")
    if 선언된_크기 is not None:
        try:
            if int(선언된_크기) > settings.max_audio_bytes:
                return _error(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    "AUDIO_TOO_LARGE",
                    f"오디오가 {선언된_크기}바이트로 상한 {settings.max_audio_bytes}바이트를 넘었다.",
                )
        except ValueError:
            # 숫자가 아닌 Content-Length는 못 믿는다. 아래 누적 합계가 막는다.
            pass

    조각들: list[bytes] = []
    받은_크기 = 0
    async for 조각 in request.stream():
        받은_크기 += len(조각)
        if 받은_크기 > settings.max_audio_bytes:
            # 더 읽지 않고 여기서 끊는다. 남은 본문을 메모리에 쌓지 않는 것이 요점이다.
            조각들.clear()
            return _error(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "AUDIO_TOO_LARGE",
                f"오디오가 상한 {settings.max_audio_bytes}바이트를 넘어 받는 중에 끊었다.",
            )
        조각들.append(조각)

    audio_bytes = b"".join(조각들)
    조각들.clear()

    if not audio_bytes:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "EMPTY_REQUEST_BODY",
            "요청 본문에 오디오가 없다.",
        )

    try:
        # 전사는 CPU/GPU를 오래 붙잡으므로 이벤트 루프를 막지 않도록 스레드로 넘긴다.
        # 그래야 전사 중에도 /health가 응답한다.
        result = await run_in_threadpool(transcriber.transcribe, audio_bytes)
    except AudioDecodeError as exc:
        logger.warning("오디오 디코딩 실패 — %s", exc)
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "AUDIO_DECODE_FAILED",
            f"오디오를 디코딩하지 못했다: {exc}",
        )
    except TranscriptionFailedError as exc:
        # 오디오 탓이 아니다. 422로 내려보내면 백엔드가 "다시 말해 달라"로 오진한다.
        logger.error("전사 실패 — 환경 문제다: %s", exc)
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STT_FAILED",
            f"오디오는 받았지만 전사에 실패했다: {exc}",
        )

    logger.info(
        "전사 완료 — 오디오 %.2f초, 처리 %.2f초, 글자 %d자",
        result.audio_seconds,
        result.processing_seconds,
        len(result.text),
    )

    return TranscriptionResponse(
        text=result.text,
        audio_seconds=round(result.audio_seconds, 2),
        processing_seconds=round(result.processing_seconds, 2),
    )
