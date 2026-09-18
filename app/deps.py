"""라우터가 쓰는 공용 의존성.

기동 시 만들어 `app.state`에 올려둔 객체를 라우터에 꽂아준다.
"""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.stt import Transcriber


def get_settings(request: Request) -> Settings:
    """기동 시 읽어둔 설정을 돌려준다."""
    return request.app.state.settings


def get_transcriber(request: Request) -> Transcriber:
    """기동 시 올려둔 전사기를 돌려준다."""
    return request.app.state.transcriber
