"""`음성 서비스`가 주고받는 응답 모델.

Spring이 이 서비스의 유일한 호출자다(ADR-0008). 응답에 판단을 담지 않는다 —
빈 전사를 오류로 만들지 않고 빈 문자열로 돌려주는 것도 같은 이유다.
`발화 턴`을 소모할지 말지는 백엔드가 정한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """헬스 체크 응답. Spring이 세션 시작 전에 훈련 환경 준비 여부를 확인할 때 쓴다."""

    status: str = Field(description="모델까지 올라와 요청을 받을 수 있으면 'ok'")
    stt_model: str = Field(description="올라온 faster-whisper 모델 크기")
    stt_device: str = Field(description="추론 장치 — 'cuda' 또는 'cpu'")
    stt_compute_type: str = Field(description="양자화 방식 — 예: float16, int8")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "ok",
                    "stt_model": "small",
                    "stt_device": "cuda",
                    "stt_compute_type": "float16",
                }
            ]
        }
    }


class TranscriptionResponse(BaseModel):
    """전사 결과.

    `text`는 사용자가 말한 내용을 그대로 옮긴 것이다. 말소리가 없었으면 빈 문자열이며,
    이때 `발화 턴`을 소모하지 않고 다시 말하게 안내하는 것은 백엔드의 판단이다.
    """

    text: str = Field(description="전사된 한국어 텍스트. 말소리가 없으면 빈 문자열")
    audio_seconds: float = Field(description="받은 오디오의 길이(초)")
    processing_seconds: float = Field(
        description="전사에 걸린 시간(초). 턴 지연 측정에 쓴다"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "죄송합니다 손님, 규정상 그건 어렵습니다.",
                    "audio_seconds": 3.4,
                    "processing_seconds": 1.12,
                }
            ]
        }
    }


class ErrorResponse(BaseModel):
    """오류 응답.

    사용자에게 보여줄 문구는 백엔드가 정한다. 여기서는 백엔드가 분기할 수 있는
    오류 코드와, 개발자가 읽을 설명만 내려보낸다.
    """

    error_code: str = Field(description="백엔드가 분기에 쓰는 코드")
    message: str = Field(description="개발자용 설명. 그대로 사용자에게 보여주지 않는다")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "error_code": "AUDIO_DECODE_FAILED",
                    "message": "오디오를 디코딩하지 못했다. 지원하지 않는 형식일 수 있다.",
                }
            ]
        }
    }
