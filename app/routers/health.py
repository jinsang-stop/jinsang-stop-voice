"""헬스 체크.

Spring은 `훈련 세션`을 시작하기 전에 이 엔드포인트로 `음성 서비스`가 준비됐는지 확인한다.
모델이 아직 올라오지 않았으면 200을 주지 않는다 — 그래야 백엔드가
"훈련 환경이 준비되지 않았다"로 세션 시작을 거절할 수 있다(슬라이스 #4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.config import Settings
from app.deps import get_settings, get_synthesizer, get_transcriber
from app.schemas import ErrorResponse, HealthResponse
from app.stt import Transcriber
from app.tts import Synthesizer

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="음성 서비스 준비 여부 확인",
    description=(
        "전사와 합성이 **둘 다** 올라와 요청을 받을 수 있으면 200과 `status: ok`를 돌려준다.\n\n"
        "Spring은 `훈련 세션` 시작 전에 이것을 확인하고, 200이 아니면 세션을 만들지 않는다.\n\n"
        "`추론 서비스`는 별도 프로세스이므로 여기서 확인하지 않는다 — 백엔드가 8081을 따로 본다."
    ),
    response_model=HealthResponse,
    response_description="요청을 받을 수 있는 상태",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": (
                "전사 모델(`STT_NOT_READY`) 또는 합성 모델(`TTS_NOT_READY`)이"
                " 아직 올라오지 않아 요청을 받을 수 없다"
            ),
        },
    },
)
def health(
    settings: Settings = Depends(get_settings),
    transcriber: Transcriber = Depends(get_transcriber),
    synthesizer: Synthesizer = Depends(get_synthesizer),
):
    """전사와 합성 모델 로딩까지 끝났는지 확인한다."""
    if not transcriber.is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                error_code="STT_NOT_READY",
                message="faster-whisper 모델이 아직 로딩되지 않았다.",
            ).model_dump(),
        )

    if not synthesizer.is_ready:
        # 전사만 되고 합성이 안 되면 `민원인`이 말을 못 한다. 온전한 `훈련 세션`이 아니다.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                error_code="TTS_NOT_READY",
                message="MeloTTS 모델이 아직 로딩되지 않았다.",
            ).model_dump(),
        )

    return HealthResponse(
        status="ok",
        stt_model=settings.stt_model,
        stt_device=settings.stt_device,
        stt_compute_type=settings.stt_compute_type,
        tts_language="KR",
        tts_device="cpu",
        tts_sample_rate=synthesizer.sample_rate or 0,
    )
