"""실제 MeloTTS를 태우는 통합 검증.

모델을 내려받고 실제로 합성하므로 느리다. 기본으로는 건너뛰고, 명시적으로 켤 때만 돈다.

    JINSANGSTOP_RUN_INTEGRATION=1 python -m pytest tests/test_tts_integration.py -v

이슈 #2의 완료 조건 중 하나를 여기서 기계로 확인한다.
- 한국어 문장을 보내면 재생 가능한 음성이 돌아오고 파일이 남지 않는다.

"재생 가능한 음성"을 파형이 있다는 것만으로 주장하지 않는다. 합성한 음성을 이 서비스의
전사기(faster-whisper)로 되돌려, 알아들을 수 있는 한국어인지까지 확인한다.
"""

from __future__ import annotations

import os
import tempfile
import wave
from io import BytesIO
from pathlib import Path

import pytest

from app.config import REPO_ROOT, load_settings
from app.stt import Transcriber
from app.tts import Synthesizer

pytestmark = pytest.mark.skipif(
    os.environ.get("JINSANGSTOP_RUN_INTEGRATION", "") != "1",
    reason="실제 모델을 태우는 검증이다. JINSANGSTOP_RUN_INTEGRATION=1로 켠다",
)

문장 = "죄송합니다 손님. 규정상 그건 어렵습니다."
핵심어 = ["죄송", "손님", "어렵"]


@pytest.fixture(scope="module")
def 합성기() -> Synthesizer:
    """모델을 한 번만 올려 모듈 안 테스트가 나눠 쓴다. 예열은 끄고 시간을 아낀다."""
    설정 = load_settings()
    합성기 = Synthesizer(설정)
    # 예열까지 하면 모듈 준비가 두 배로 걸린다. 첫 합성이 느린 것은 여기서 문제가 아니다.
    합성기._settings = 설정.__class__(**{**설정.__dict__, "tts_warmup": False})
    합성기.load()
    return 합성기


def test_한국어_문장이_재생_가능한_WAV로_합성된다(합성기):
    """이슈 #2 완료 조건: 한국어 문장을 보내면 재생 가능한 음성이 돌아온다."""
    결과 = 합성기.synthesize(문장)

    # 머리표가 맞아야 재생기가 열 수 있다.
    assert 결과.wav[:4] == b"RIFF"
    assert 결과.wav[8:12] == b"WAVE"
    assert 결과.sample_rate == 44100

    # WAV로 실제로 열리고, 길이와 형식이 앞뒤가 맞아야 한다.
    with wave.open(BytesIO(결과.wav), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 44100
        프레임수 = w.getnframes()
    assert 프레임수 > 0
    assert 결과.audio_seconds == pytest.approx(프레임수 / 44100, abs=0.01)
    # 짧은 한 문장이 수십 초가 되면 무언가 잘못된 것이다.
    assert 1.0 < 결과.audio_seconds < 20.0


def test_합성한_음성을_전사하면_같은_말이_나온다(합성기):
    """파형이 있다는 것만으로 "재생 가능"을 주장하지 않는다.

    합성 -> 전사 왕복으로 알아들을 수 있는 한국어인지 확인한다. 전사가 토씨까지 같을 것을
    요구하지는 않는다 — 작은 전사 모델이 합성음을 다루므로 핵심 낱말만 본다.
    """
    결과 = 합성기.synthesize(문장)

    전사기 = Transcriber(load_settings())
    전사기.load()
    전사 = 전사기.transcribe(결과.wav)

    assert 전사.text, "합성한 음성에서 아무 말도 전사되지 않았다"
    누락 = [낱말 for 낱말 in 핵심어 if 낱말 not in 전사.text]
    assert not 누락, f"전사 '{전사.text}'에 {누락}이(가) 없다"


def test_빠르게_말하면_오디오가_짧아진다(합성기):
    """speed 가 실제로 먹는지. MeloTTS가 노출하는 조절 값은 speed와 speaker_id뿐이다."""
    보통 = 합성기.synthesize(문장, speed=1.0)
    빠르게 = 합성기.synthesize(문장, speed=1.5)

    assert 빠르게.audio_seconds < 보통.audio_seconds


def test_합성은_디스크에_오디오를_남기지_않는다(합성기):
    """이슈 #2 완료 조건: 파일이 남지 않는다.

    ADR-0006의 "민원인 TTS 음성도 재생 후 보관하지 않는다"를 파일 목록으로 확인한다.
    지웠는지가 아니라 **애초에 만들지 않았는지**를 본다.
    """
    오디오_확장자 = {".wav", ".mp3", ".webm", ".ogg", ".m4a", ".flac"}

    def 오디오_목록(뿌리: Path) -> set[Path]:
        return {
            경로
            for 경로 in 뿌리.glob("*")
            if 경로.is_file() and 경로.suffix.lower() in 오디오_확장자
        }

    임시_폴더 = Path(tempfile.gettempdir())
    전_임시 = 오디오_목록(임시_폴더)
    전_저장소 = 오디오_목록(REPO_ROOT)

    합성기.synthesize(문장)

    assert 오디오_목록(임시_폴더) - 전_임시 == set(), "임시 폴더에 오디오가 새로 생겼다"
    assert 오디오_목록(REPO_ROOT) - 전_저장소 == set(), "저장소에 오디오가 새로 생겼다"
