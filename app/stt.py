"""faster-whisper 전사기.

오디오는 **디스크를 거치지 않는다**. 받은 바이트를 메모리 버퍼에 담아 그대로
faster-whisper에 넘긴다(설치된 1.2.1에서 `transcribe(audio)`가 `BinaryIO`를 받는 것을 확인했다).
ADR-0006이 "사용자 음성 파일은 전사가 끝나는 즉시 폐기한다"고 정했으므로,
임시 파일을 만들었다가 지우는 것이 아니라 애초에 만들지 않는 쪽을 택했다.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass

import av
from faster_whisper import WhisperModel

from app.config import Settings

logger = logging.getLogger(__name__)

# 전사 대상 언어를 한국어로 고정한다. MVP는 한국어 훈련만 다루므로
# 언어 자동 감지에 시간을 쓰지 않고 오인식 여지도 남기지 않는다.
TARGET_LANGUAGE = "ko"


class AudioDecodeError(Exception):
    """받은 바이트를 오디오로 디코딩하지 못했을 때 — 보낸 쪽 문제다.

    PyAV가 던지는 `av.FFmpegError` 계열만 여기로 온다. 확인한 바로는 쓰레기 바이트와
    빈 바이트 모두 `av.error.InvalidDataError`(→ `av.FFmpegError` 하위)로 나온다.
    """


class TranscriptionFailedError(Exception):
    """오디오는 멀쩡한데 전사가 실패했을 때 — 이쪽 문제다.

    GPU 메모리 부족처럼 환경에서 비롯한 실패가 여기 온다. `음성 서비스`와
    `추론 서비스`가 시연 장비의 GPU를 나눠 쓰므로(ADR-0009) 현실적인 상황이다.
    이것을 디코딩 실패와 같은 코드로 내려보내면 백엔드가 사용자에게 "다시 말해 달라"를
    띄우고, 사용자는 같은 말을 반복하는데 원인은 GPU에 있게 된다.
    """


@dataclass
class TranscriptionResult:
    """전사 결과 — 라우터가 응답 모델로 옮겨 담는다."""

    text: str
    audio_seconds: float
    processing_seconds: float


class Transcriber:
    """faster-whisper 모델을 한 번 올려두고 재사용한다.

    모델 로딩은 수 초에서 수십 초가 걸리므로 요청마다 하지 않고 기동 시 한 번만 한다.
    `추론 서비스`와 GPU를 나눠 쓰므로(ADR-0009) 모델 인스턴스도 하나만 유지한다.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: WhisperModel | None = None
        # 한 번에 한 건만 전사한다. 동시 훈련 세션이 하나뿐이므로(ADR-0009) 줄을 세워도
        # 사용자가 기다리지 않고, 모델 인스턴스를 동시에 건드리는 위험만 사라진다.
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        """모델이 올라와 요청을 받을 수 있는 상태인지."""
        return self._model is not None

    def load(self) -> None:
        """모델을 올린다. 가중치가 없으면 이때 내려받는다."""
        settings = self._settings
        settings.stt_download_root.mkdir(parents=True, exist_ok=True)
        logger.info(
            "faster-whisper 모델 로딩 — model=%s device=%s compute_type=%s",
            settings.stt_model,
            settings.stt_device,
            settings.stt_compute_type,
        )
        started = time.perf_counter()
        self._model = WhisperModel(
            settings.stt_model,
            device=settings.stt_device,
            compute_type=settings.stt_compute_type,
            download_root=str(settings.stt_download_root),
        )
        logger.info("모델 로딩 완료 — %.1f초", time.perf_counter() - started)

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """오디오 바이트를 한국어 텍스트로 옮긴다.

        말소리가 없으면 예외를 던지지 않고 빈 문자열을 돌려준다 — 이 서비스는
        변환만 하고 판단하지 않는다. 빈 전사를 어떻게 다룰지는 백엔드가 정한다.
        """
        if self._model is None:
            raise RuntimeError("모델이 아직 로딩되지 않았다")

        started = time.perf_counter()
        # 디스크를 거치지 않는 메모리 버퍼. 요청 처리가 끝나면 함께 사라진다.
        buffer = io.BytesIO(audio_bytes)

        with self._lock:
            try:
                segments, info = self._model.transcribe(
                    buffer,
                    language=TARGET_LANGUAGE,
                    beam_size=self._settings.stt_beam_size,
                    # 무음 구간을 걸러 헛된 문장이 만들어지는 것을 줄인다.
                    vad_filter=True,
                )
                # faster-whisper의 전사는 지연 평가라 여기서 실제로 돌아간다.
                text = "".join(segment.text for segment in segments).strip()
                audio_seconds = float(info.duration)
            except av.FFmpegError as exc:
                # 보낸 오디오를 열지 못한 것이다. 형식이 아니거나 깨졌다.
                raise AudioDecodeError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — 남은 전부는 이쪽 장애로 취급한다
                # 오디오 탓으로 돌리지 않는다. GPU 메모리 부족·모델 비정상 등이 여기 온다.
                logger.exception("전사가 실패했다 — 오디오 문제가 아니다")
                raise TranscriptionFailedError(str(exc)) from exc
            finally:
                # 버퍼를 즉시 비운다. ADR-0006의 "전사 직후 폐기"를 코드로 지킨다.
                buffer.close()

        return TranscriptionResult(
            text=text,
            audio_seconds=audio_seconds,
            processing_seconds=time.perf_counter() - started,
        )
