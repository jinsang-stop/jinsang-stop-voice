"""한국어 G2P 대체가 발음을 바꾸지 않았는지 확인한다.

윈도에서 `g2pkk`가 찾는 `eunjeon`은 Python 3.6용 휠까지만 있어 3.13에서는 쓸 수 없다.
그래서 같은 mecab-ko 사전을 쓰는 `mecab-ko`로 갈아끼웠다(`app/korean_g2p.py`).
**갈아끼운 뒤에도 발음이 같은지**를 `g2pkk`가 스스로 docstring에 적어둔 예시로 확인한다.

모델을 내려받지 않으므로 빠르다 — 계약 테스트와 함께 항상 돈다.
"""

from __future__ import annotations

import pytest

from app.korean_g2p import MecabKoTagger, apply

# g2pkk 의 G2p.__call__ docstring 에 적힌 입력과 최종 출력.
# 숫자 읽기(3개 -> 세개), 영어 음차(mp3 -> 엠피쓰리, file -> 파일),
# 경음화(다운받고 -> 다운받꼬), 음절 끝 중화(있다 -> 읻따)가 한꺼번에 걸린다.
문서_예시_입력 = "나의 친구가 mp3 file 3개를 다운받고 있다"
문서_예시_출력 = "나의 친구가 엠피쓰리 파일 세개를 다운받꼬 읻따"


@pytest.fixture(scope="module")
def g2p():
    """대체를 적용한 뒤 G2p 하나를 만들어 모듈 안에서 나눠 쓴다."""
    apply()
    from g2pkk import G2p

    return G2p()


def test_문서에_적힌_예시_발음을_그대로_재현한다(g2p):
    """사전이 바뀌어 발음이 달라졌다면 이 테스트가 먼저 깨진다."""
    assert g2p(문서_예시_입력) == 문서_예시_출력


@pytest.mark.parametrize(
    "입력, 기대",
    [
        # 비음화: 죄송합니다 -> 죄송함니다
        ("죄송합니다", "죄송함니다"),
        # 연음: 환불은 -> 환부른 계열, 영수증이 -> 녕수증이
        ("환불은 영수증이 있어야 가능합니다.", "환부르 녕수증이 이써야 가능함니다."),
    ],
)
def test_흔한_응대_문장의_발음(g2p, 입력, 기대):
    """`민원인` 응대에서 실제로 나올 문장들. 회귀를 잡기 위한 고정 기대값이다."""
    assert g2p(입력) == 기대


def test_형태소_태그를_g2pkk가_기대하는_형태로_준다():
    """`g2pkk`의 annotate 는 (표면형, 품사태그) 목록과 NNBC 태그를 기대한다."""
    태거 = MecabKoTagger()
    결과 = 태거.pos("세개를")

    assert all(isinstance(항목, tuple) and len(항목) == 2 for 항목 in 결과)
    # 표면형을 이으면 공백 없는 원문이 되어야 annotate 가 결과를 버리지 않는다.
    assert "".join(표면형 for 표면형, _ in 결과) == "세개를"
    # 의존명사(NNBC)를 알아봐야 숫자 읽기가 "세개"로 붙는다.
    assert any(태그 == "NNBC" for _, 태그 in 결과)


def test_두_번_적용해도_문제없다():
    """기동 경로에서 여러 번 불릴 수 있다."""
    apply()
    apply()
    from g2pkk import G2p

    assert G2p()(문서_예시_입력) == 문서_예시_출력
