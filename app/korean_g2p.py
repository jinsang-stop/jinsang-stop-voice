"""한국어 G2P가 윈도에서 형태소 분석기를 찾도록 맞춰주는 얇은 층.

MeloTTS의 한국어 경로는 `g2pkk`로 한글을 발음대로 바꾼다. 그 과정의 한 단계(`annotate`)가
형태소 품사를 필요로 하는데, `g2pkk`는 윈도에서 **`eunjeon`만** 찾는다. 그런데 `eunjeon`은
PyPI에 Python 3.6용 윈도 휠까지만 올라와 있어 3.13에서는 소스 빌드가 유일하고, 그러려면
Visual Studio C++ 빌드 도구가 필요하다. 시연 장비와 개발 기계에 빌드 도구를 얹지 않기 위해,
같은 mecab-ko 사전을 쓰는 `mecab-ko` 패키지(3.13 윈도 휠이 있다)로 갈아끼운다.

**발음이 달라지지 않는지 확인했다.** `g2pkk`가 docstring에 적어둔 예시
"나의 친구가 mp3 file 3개를 다운받고 있다" → "나의 친구가 엠피쓰리 파일 세개를 다운받꼬 읻따"를
이 층을 끼운 상태에서 그대로 재현한다(`tests/test_korean_g2p.py`).
사전이 같은 계열이고, `g2pkk`가 쓰는 것은 품사 태그 문자열뿐이어서 결과가 일치한다.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# 패치를 두 번 걸지 않기 위한 표시. 기동 중 여러 번 불려도 한 번만 건다.
_적용됨 = False
_잠금 = threading.Lock()


class MecabKoTagger:
    """`g2pkk`가 기대하는 `.pos()`를 `mecab_ko.Tagger` 위에 올린다.

    `g2pkk`는 `mecab.pos(문장)`이 `(표면형, 품사태그)` 목록을 돌려주기를 기대한다.
    `mecab_ko`는 저수준 바인딩이라 그 편의 메서드가 없으므로 여기서 만들어 준다.
    """

    def __init__(self) -> None:
        import mecab_ko

        self._tagger = mecab_ko.Tagger()

    def pos(self, text: str) -> list[tuple[str, str]]:
        """문장을 (표면형, 품사태그) 목록으로 쪼갠다."""
        결과: list[tuple[str, str]] = []
        for 줄 in self._tagger.parse(text).splitlines():
            # mecab 출력의 끝 표시와 빈 줄은 건너뛴다.
            if 줄 == "EOS" or not 줄.strip():
                continue
            # 형식: "표면형<탭>품사,자질,자질,..." — 품사는 첫 자질이다.
            표면형, _, 자질 = 줄.partition("\t")
            결과.append((표면형, 자질.split(",")[0]))
        return 결과


def apply() -> None:
    """`g2pkk`가 `eunjeon` 대신 `mecab-ko`를 쓰게 만든다.

    **첫 합성보다 먼저 불러야 한다.** `g2pkk.G2p`는 MeloTTS가 첫 요청에서 만들므로,
    클래스 메서드를 미리 갈아끼워 두면 그때 만들어지는 인스턴스가 이걸 쓴다.
    """
    global _적용됨
    with _잠금:
        if _적용됨:
            return

        import g2pkk.g2pkk as g2pkk_모듈

        # check_mecab은 없으면 pip install을 실행해 버리므로 통째로 무력화한다.
        # 서비스가 기동 중에 패키지를 설치하려 드는 일은 없어야 한다.
        g2pkk_모듈.G2p.check_mecab = lambda self: None
        g2pkk_모듈.G2p.get_mecab = lambda self: MecabKoTagger()

        _적용됨 = True
        logger.info("한국어 G2P의 형태소 분석기를 mecab-ko로 맞췄다")
