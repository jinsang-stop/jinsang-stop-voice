# calmdesk-voice — 진상 멈춰 `음성 서비스`(faster-whisper · MeloTTS) · `추론 서비스`(llama.cpp) 실행 설정

제품명은 「진상 멈춰」, 코드 식별자는 `calmdesk`.

## 먼저 읽을 것

도메인 문서는 이 저장소에 없다. [jinsang-stop/calmdesk](https://github.com/jinsang-stop/calmdesk)에서 읽는다
(나란히 클론했다면 `../calmdesk`).

1. `CONTEXT.md` — 용어집. 식별자는 여기 용어로 짓는다.
2. `docs/adr/` — 작업 영역과 닿는 결정.
3. `docs/PRD-v2.md` — 현재 PRD. `docs/PRD.md`(v1)는 구현 근거로 쓰지 않는다.

## 작업 규약

커밋·브랜치·이슈·PR 양식은 `CONTRIBUTING.md`. 저장소 전역 규약보다 이 파일이 우선한다.

## 이슈

이 저장소의 `[Feat]` 이슈는 `jinsang-stop/calmdesk`의 `[Slice]` 이슈 하위 이슈다.
상태 복원은 `gh issue view <번호> --comments`로 이 이슈와 상위 슬라이스를 둘 다 읽는다.
공통 계약(필드·상태·오류 전달)은 슬라이스 이슈가 정본이다.
