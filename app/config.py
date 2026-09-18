"""`음성 서비스` 설정.

모든 값은 환경변수로 주입한다. 값이 없으면 여기 적힌 기본값을 쓴다.

ADR-0008에 따라 이 서비스는 Spring만 호출한다. 브라우저도 외부도 직접 부르지 않는다.
그래서 바인딩 주소의 기본값은 언제나 루프백(127.0.0.1)이고, 이 기본값을 바꾸는 것은
배포 결정이 아니라 ADR을 어기는 일이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 저장소 루트 — 모델 가중치를 여기 models/ 아래에 받는다(.gitignore에 잡혀 있다).
REPO_ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str) -> str:
    """환경변수를 읽되, 없거나 공백뿐이면 기본값을 돌려준다."""
    return os.environ.get(key, "").strip() or default


def _env_int(key: str, default: int) -> int:
    """정수 환경변수. 숫자가 아니면 설정 실수이므로 조용히 넘기지 않고 터뜨린다."""
    raw = _env(key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"환경변수 {key}는 정수여야 하는데 '{raw}'이(가) 들어왔다") from exc


def detect_device() -> str:
    """CUDA를 쓸 수 있으면 'cuda', 아니면 'cpu'.

    ctranslate2가 실제로 인식하는 CUDA 장치 수로 판단한다. NVIDIA 드라이버나
    cuBLAS가 없는 개발용 노트북에서는 0이 나오므로 자동으로 CPU로 떨어진다.
    """
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:  # noqa: BLE001 — 장치 탐지 실패는 CPU 폴백으로 충분하다
        pass
    return "cpu"


@dataclass(frozen=True)
class Settings:
    """서비스 기동에 필요한 설정 묶음."""

    # --- HTTP ---
    host: str
    port: int

    # --- STT(faster-whisper) ---
    stt_model: str
    stt_device: str
    stt_compute_type: str
    stt_beam_size: int
    stt_download_root: Path

    # 받아들일 오디오의 최대 크기(바이트). 오디오를 통째로 메모리에 올리므로
    # 상한이 없으면 큰 요청 하나가 서비스를 넘어뜨린다.
    max_audio_bytes: int


def load_settings() -> Settings:
    """환경변수를 읽어 Settings를 만든다."""
    device = _env("JINSANGSTOP_STT_DEVICE", "auto")
    if device == "auto":
        device = detect_device()

    # compute_type 기본값은 장치마다 다르다.
    # GPU: float16 — 정확도를 유지하면서 VRAM을 아낀다.
    # CPU: int8 — 개발용 노트북에서 현실적인 속도가 나오는 유일한 선택.
    compute_type = _env(
        "JINSANGSTOP_STT_COMPUTE_TYPE",
        "float16" if device == "cuda" else "int8",
    )

    return Settings(
        host=_env("JINSANGSTOP_VOICE_HOST", "127.0.0.1"),
        port=_env_int("JINSANGSTOP_VOICE_PORT", 8000),
        stt_model=_env("JINSANGSTOP_STT_MODEL", "small"),
        stt_device=device,
        stt_compute_type=compute_type,
        stt_beam_size=_env_int("JINSANGSTOP_STT_BEAM_SIZE", 5),
        stt_download_root=Path(
            _env("JINSANGSTOP_STT_DOWNLOAD_ROOT", str(REPO_ROOT / "models"))
        ),
        max_audio_bytes=_env_int("JINSANGSTOP_MAX_AUDIO_BYTES", 25 * 1024 * 1024),
    )
