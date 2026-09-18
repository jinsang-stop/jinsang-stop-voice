"""실제 faster-whisper 모델을 태우는 통합 검증.

모델 가중치를 내려받고 실제로 전사하므로 느리다. 기본으로는 건너뛰고, 명시적으로 켤 때만 돈다.

    JINSANGSTOP_RUN_INTEGRATION=1 python -m pytest tests/test_stt_integration.py -v

이슈 #1의 완료 조건 중 두 개를 여기서 기계로 확인한다.
- 한국어 녹음 파일을 보내면 전사 텍스트가 돌아온다.
- 요청 처리 후 서비스 디렉터리와 임시 폴더에 오디오 파일이 남지 않는다.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import pytest

from app.config import REPO_ROOT, load_settings
from app.stt import Transcriber

pytestmark = pytest.mark.skipif(
    os.environ.get("JINSANGSTOP_RUN_INTEGRATION", "") != "1",
    reason="실제 모델을 태우는 검증이다. JINSANGSTOP_RUN_INTEGRATION=1로 켠다",
)

# 합성해 읽힐 문장. 전사가 토씨까지 같을 것을 요구하지 않고 핵심 낱말만 본다.
샘플_문장 = "죄송합니다 손님. 규정상 그건 어렵습니다."
샘플_핵심어 = ["죄송", "손님", "규정"]


@pytest.fixture(scope="module")
def 전사기() -> Transcriber:
    """모델을 한 번만 올려 모듈 안 테스트가 나눠 쓴다."""
    transcriber = Transcriber(load_settings())
    transcriber.load()
    return transcriber


def 무음_wav(초: float = 3.0) -> bytes:
    """말소리가 없는 16kHz 모노 WAV를 메모리에 만든다."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * 초))
    return buffer.getvalue()


def 한국어_wav(문장: str, 작업_폴더: Path) -> bytes | None:
    """윈도 내장 TTS(ko-KR)로 한국어 WAV를 만들어 바이트로 읽는다.

    마이크 녹음을 대신하는 것이다. ko-KR 음성이 없는 기계에서는 None을 돌려주고
    호출한 테스트가 건너뛴다 — 없다고 실패로 만들 일은 아니다.

    TTS는 파일로만 내보낼 수 있어 한 번 디스크를 거치지만, 바이트를 읽는 즉시 지운다.
    오디오를 남기지 않는지 확인하는 검증이 스스로 오디오를 남기고 있으면 안 된다(ADR-0006).
    """
    대상 = 작업_폴더 / "한국어샘플.wav"
    스크립트 = f"""
Add-Type -AssemblyName System.Speech
$합성기 = New-Object System.Speech.Synthesis.SpeechSynthesizer
$한국어음성 = $합성기.GetInstalledVoices() |
    Where-Object {{ $_.VoiceInfo.Culture.Name -eq 'ko-KR' }} |
    Select-Object -First 1
if (-not $한국어음성) {{ exit 2 }}
$합성기.SelectVoice($한국어음성.VoiceInfo.Name)
$합성기.Rate = -1
$합성기.SetOutputToWaveFile('{대상}')
$합성기.Speak('{문장}')
$합성기.SetOutputToNull()
$합성기.Dispose()
"""
    완료 = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", 스크립트],
        capture_output=True,
        timeout=120,
    )
    if 완료.returncode != 0 or not 대상.exists():
        return None
    try:
        return 대상.read_bytes()
    finally:
        대상.unlink(missing_ok=True)


def test_한국어_음성이_전사된다(전사기, tmp_path):
    """이슈 #1 완료 조건: 한국어 녹음 파일을 보내면 전사 텍스트가 돌아온다."""
    오디오 = 한국어_wav(샘플_문장, tmp_path)
    if 오디오 is None:
        pytest.skip("이 기계에 ko-KR TTS 음성이 없어 한국어 샘플을 만들 수 없다")

    결과 = 전사기.transcribe(오디오)

    assert 결과.text, "전사 결과가 비어 있다"
    누락 = [낱말 for 낱말 in 샘플_핵심어 if 낱말 not in 결과.text]
    assert not 누락, f"전사 '{결과.text}'에 {누락}이(가) 없다"
    assert 결과.audio_seconds > 0
    assert 결과.processing_seconds > 0


def test_말소리가_없으면_빈_문자열이다(전사기):
    """`음성 서비스`는 판단하지 않는다 — 빈 전사를 오류로 만들지 않는다(슬라이스 #4)."""
    결과 = 전사기.transcribe(무음_wav())

    assert 결과.text == ""
    assert 결과.audio_seconds == pytest.approx(3.0, abs=0.2)


def test_전사는_디스크에_오디오를_남기지_않는다(전사기, tmp_path):
    """이슈 #1 완료 조건: 처리 후 서비스 디렉터리와 임시 폴더에 오디오가 남지 않는다.

    ADR-0006의 "전사 직후 폐기"를 코드가 지키는지 파일 목록으로 확인한다.
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

    오디오 = 한국어_wav(샘플_문장, tmp_path) or 무음_wav()
    전사기.transcribe(오디오)

    assert 오디오_목록(임시_폴더) - 전_임시 == set(), "임시 폴더에 오디오가 새로 생겼다"
    assert 오디오_목록(REPO_ROOT) - 전_저장소 == set(), "저장소에 오디오가 새로 생겼다"
