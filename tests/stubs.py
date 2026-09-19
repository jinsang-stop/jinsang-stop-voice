"""여러 테스트가 나눠 쓰는 대역(stub).

실제 모델을 올리지 않고 라우터 분기만 보기 위한 것이다.
모델을 실제로 태우는 검증은 `tests/test_*_integration.py`가 맡는다.
"""

from __future__ import annotations

from app.stt import AudioDecodeError, TranscriptionResult
from app.tts import SynthesisResult

# 대역이 돌려주는 최소한의 WAV — 44바이트 헤더에 프레임 0개.
빈_WAV = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    b"D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
)


class StubTranscriber:
    """모델 없이 전사 라우터를 시험하기 위한 대역."""

    def __init__(
        self,
        *,
        ready: bool = True,
        raises: BaseException | None = None,
        text: str = "안녕하세요",
    ) -> None:
        self.is_ready = ready
        self._raises = raises
        self._text = text
        self.received: bytes | None = None

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self.received = audio_bytes
        if self._raises is not None:
            raise self._raises
        return TranscriptionResult(
            text=self._text, audio_seconds=1.5, processing_seconds=0.3
        )


class StubSynthesizer:
    """모델 없이 합성 라우터를 시험하기 위한 대역."""

    def __init__(
        self,
        *,
        ready: bool = True,
        raises: BaseException | None = None,
        wav: bytes = 빈_WAV,
    ) -> None:
        self.is_ready = ready
        self.sample_rate = 44100
        self._raises = raises
        self._wav = wav
        # 라우터가 무엇을 넘겼는지 확인하려고 기록해 둔다.
        self.received_text: str | None = None
        self.received_speed: float | None = None

    def synthesize(self, text: str, speed: float = 1.0) -> SynthesisResult:
        self.received_text = text
        self.received_speed = speed
        if self._raises is not None:
            raise self._raises
        return SynthesisResult(
            wav=self._wav,
            audio_seconds=2.5,
            processing_seconds=1.1,
            sample_rate=44100,
        )


__all__ = ["StubTranscriber", "StubSynthesizer", "AudioDecodeError", "빈_WAV"]
