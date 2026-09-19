"""MeloTTS 한국어 합성기.

합성한 오디오는 **디스크를 거치지 않는다**. MeloTTS의 `tts_to_file(..., output_path=None)`이
파형을 numpy 배열로 돌려주는 것을 확인했으므로, 그 배열을 메모리에서 WAV로 포장해 그대로
응답 본문에 싣는다. ADR-0006이 "민원인 TTS 음성도 재생 후 보관하지 않는다"고 정했으므로,
파일을 만들었다가 지우는 것이 아니라 애초에 만들지 않는 쪽을 택했다 — `음성 서비스`의
전사 경로(`app/stt.py`)와 같은 판단이다.

ADR-0009에 따라 **CPU로 돌린다.** 시연 장비의 VRAM 8GB는 STT와 `추론 서비스`가 나눠 쓰므로
TTS에 GPU를 내주지 않는다.
"""

from __future__ import annotations

import io
import logging
import threading
import time
import wave
from dataclasses import dataclass

import numpy as np

from app.config import Settings

logger = logging.getLogger(__name__)

# MeloTTS의 한국어 모델과 화자 식별자. 확인한 바로 화자는 'KR' 하나뿐이다.
TARGET_LANGUAGE = "KR"
TARGET_SPEAKER = "KR"


class SynthesisFailedError(Exception):
    """텍스트는 받았는데 합성이 실패했을 때 — 이쪽 문제다.

    보낸 텍스트가 잘못된 경우와 이쪽 장애를 **나누지 않는다.** MeloTTS가 어떤 입력에서
    실패하는지 신뢰할 만하게 가려낼 방법이 없어서, 가려낼 수 있는 척하는 대신 전부
    이쪽 문제로 보고한다. 길이나 빈 문자열처럼 확실히 판별되는 것만 라우터가 먼저 거른다.
    """


@dataclass
class SynthesisResult:
    """합성 결과 — 라우터가 응답으로 옮겨 담는다."""

    wav: bytes
    audio_seconds: float
    processing_seconds: float
    sample_rate: int


def _to_wav(파형: np.ndarray, sample_rate: int) -> bytes:
    """float 파형을 16비트 PCM WAV 바이트로 포장한다. 디스크를 거치지 않는다."""
    # MeloTTS는 -1.0~1.0 범위의 float32를 준다. 범위를 벗어난 값은 잘라내야
    # 16비트로 옮길 때 소리가 깨지지 않는다.
    잘린것 = np.clip(np.asarray(파형, dtype=np.float32), -1.0, 1.0)
    pcm = (잘린것 * 32767.0).astype("<i2")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buffer.getvalue()


class Synthesizer:
    """MeloTTS 모델을 한 번 올려두고 재사용한다.

    모델 로딩과 첫 합성이 느리므로(첫 호출은 워밍업이 붙어 실측 2.8배 실시간, 이후 1.2배)
    기동 시 한 번 올리고 예열까지 해 둔다. 그래야 첫 `발화 턴`만 유독 느린 일이 없다.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = None
        self._speaker_id: int | None = None
        self._sample_rate: int | None = None
        # 한 번에 한 건만 합성한다. 동시 `훈련 세션`이 하나뿐이므로(ADR-0009) 줄을 세워도
        # 사용자가 기다리지 않고, 모델 인스턴스를 동시에 건드리는 위험만 사라진다.
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        """모델이 올라와 요청을 받을 수 있는 상태인지."""
        return self._model is not None

    @property
    def sample_rate(self) -> int | None:
        """올라온 모델의 샘플레이트. 확인한 값은 44100이다."""
        return self._sample_rate

    def load(self) -> None:
        """모델을 올리고 한 번 예열한다. 가중치가 없으면 이때 내려받는다."""
        # g2pkk가 윈도에서 eunjeon을 찾지 않도록 먼저 갈아끼운다. 첫 합성보다 앞서야 한다.
        from app import korean_g2p

        korean_g2p.apply()

        from melo.api import TTS

        logger.info("MeloTTS 모델 로딩 — language=%s device=cpu", TARGET_LANGUAGE)
        started = time.perf_counter()
        # ADR-0009: TTS는 CPU에 둔다. GPU는 STT와 `추론 서비스` 몫이다.
        model = TTS(language=TARGET_LANGUAGE, device="cpu")
        self._speaker_id = model.hps.data.spk2id[TARGET_SPEAKER]
        self._sample_rate = int(model.hps.data.sampling_rate)
        self._model = model
        logger.info("모델 로딩 완료 — %.1f초", time.perf_counter() - started)

        if self._settings.tts_warmup:
            # 첫 호출에만 붙는 초기화 비용을 기동 때 치러 둔다.
            started = time.perf_counter()
            try:
                self.synthesize("예열합니다.")
                logger.info("합성 예열 완료 — %.1f초", time.perf_counter() - started)
            except SynthesisFailedError as exc:
                # 예열 실패로 기동을 막지는 않는다. 헬스 체크가 판단할 몫이다.
                logger.warning("합성 예열 실패 — 계속 진행한다: %s", exc)

    def synthesize(self, text: str, speed: float = 1.0) -> SynthesisResult:
        """한국어 텍스트를 WAV 바이트로 합성한다."""
        if self._model is None:
            raise RuntimeError("모델이 아직 로딩되지 않았다")

        started = time.perf_counter()
        with self._lock:
            try:
                파형 = self._model.tts_to_file(
                    text,
                    self._speaker_id,
                    # 출력 경로를 주지 않으면 파일을 쓰지 않고 배열을 돌려준다(ADR-0006).
                    output_path=None,
                    speed=speed,
                )
            except Exception as exc:  # noqa: BLE001 — 합성 실패를 호출자에게 코드로 전달한다
                logger.exception("합성이 실패했다")
                raise SynthesisFailedError(str(exc)) from exc

        sample_rate = self._sample_rate or 44100
        배열 = np.asarray(파형)
        wav = _to_wav(배열, sample_rate)

        return SynthesisResult(
            wav=wav,
            audio_seconds=len(배열) / sample_rate,
            processing_seconds=time.perf_counter() - started,
            sample_rate=sample_rate,
        )
