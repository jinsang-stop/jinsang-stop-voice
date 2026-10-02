"""전사 장치 자동 선택이 '쓸 수 없는 CUDA'를 고르지 않는지 확인한다.

시연 장비(RTX 5060 Ti)에서 GPU는 잡히는데 cuBLAS(`cublas64_12.dll`)가 없으면
`auto`가 cuda를 골라 모델 로딩과 /health는 성공하고 **모든 전사가 503 `STT_FAILED`**가 됐다.
cuBLAS가 실제로 올라올 때만 cuda를 고르는지를 GPU 없이 확인한다.
"""

from __future__ import annotations

import ctranslate2
import pytest

from app import config


@pytest.fixture
def gpu_한_장(monkeypatch):
    """ctranslate2가 CUDA 장치 하나를 본다고 가정한다."""
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)


def test_GPU가_있어도_cuBLAS가_없으면_CPU로_떨어진다(monkeypatch, gpu_한_장):
    monkeypatch.setattr(config, "_cublas_loadable", lambda: False)
    assert config.detect_device() == "cpu"


def test_GPU와_cuBLAS가_모두_있으면_CUDA를_고른다(monkeypatch, gpu_한_장):
    monkeypatch.setattr(config, "_cublas_loadable", lambda: True)
    assert config.detect_device() == "cuda"


def test_GPU가_없으면_CPU다(monkeypatch):
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    monkeypatch.setattr(config, "_cublas_loadable", lambda: True)
    assert config.detect_device() == "cpu"
