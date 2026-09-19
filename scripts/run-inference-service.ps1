<#
    진상 멈춰 `추론 서비스` 실행 스크립트 (ADR-0009)

    llama.cpp의 llama-server로 Qwen3.6-35B-A3B를 띄운다.
    `민원인` 대사 생성과 `태도 3축` 채점을 위한 로컬 LLM 서빙이고, Spring만 호출한다.
    프롬프트를 조립하지 않고 `시나리오 카드`와 채점 루브릭을 모른다.

    인자 기본값은 ADR-0009의 "실행 기준값" 그대로다. 환경변수로 덮어쓸 수 있다.
    `--n-cpu-moe`는 99(전문가 전부 RAM)에서 시작해, ADR-0009 자원 배치표의
    VRAM 계획값에 닿을 때까지 줄여 GPU에 더 올린다.

    내려받기 절차와 확인된 지원 범위는 README의 "추론 서비스" 절을 먼저 읽는다.

    배치 파일(.bat)이 아니라 PowerShell을 쓰는 이유: cmd는 UTF-8로 저장한 한글 주석을
    콘솔 코드페이지(cp949)로 잘못 읽어 스크립트 자체가 깨진다. `chcp`를 중간에 넣으면
    그 뒤 파싱이 어긋난다. 저장소를 UTF-8로 유지하면서 한글 주석을 쓰려면 이쪽이 맞다.
#>

$ErrorActionPreference = 'Stop'

# 저장소 루트로 이동한다 (이 스크립트는 scripts\ 안에 있다).
$저장소루트 = Split-Path -Parent $PSScriptRoot
Push-Location $저장소루트

try {
    # 환경변수가 있으면 그것을, 없으면 ADR-0009 기준값을 쓴다.
    function 환경값($이름, $기본값) {
        $값 = [Environment]::GetEnvironmentVariable($이름)
        if ([string]::IsNullOrWhiteSpace($값)) { return $기본값 }
        return $값
    }

    $llamaDir  = 환경값 'JINSANGSTOP_LLAMA_DIR'       (Join-Path $저장소루트 'tools\llama-b11026')
    $모델      = 환경값 'JINSANGSTOP_LLAMA_MODEL'     (Join-Path $저장소루트 'models\Qwen3.6-35B-A3B-Q4_K_M.gguf')
    $호스트    = 환경값 'JINSANGSTOP_LLAMA_HOST'      '127.0.0.1'
    $포트      = 환경값 'JINSANGSTOP_LLAMA_PORT'      '8081'
    $컨텍스트  = 환경값 'JINSANGSTOP_LLAMA_CTX'       '16384'
    $병렬      = 환경값 'JINSANGSTOP_LLAMA_PARALLEL'  '2'
    $ngl       = 환경값 'JINSANGSTOP_LLAMA_NGL'       '99'
    $nCpuMoe   = 환경값 'JINSANGSTOP_LLAMA_N_CPU_MOE' '99'

    $실행파일 = Join-Path $llamaDir 'llama-server.exe'

    # 있어야 할 것이 없으면 조용히 실패하지 않고 무엇이 없는지 말한다.
    if (-not (Test-Path $실행파일)) {
        Write-Error "llama-server를 찾지 못했다: $실행파일`nREADME의 '추론 서비스' 절을 보고 CUDA 빌드를 내려받아 풀어라."
        exit 1
    }
    if (-not (Test-Path $모델)) {
        Write-Error "모델 가중치를 찾지 못했다: $모델`nREADME의 '모델 내려받기' 절을 보라. 가중치는 커밋하지 않는다."
        exit 1
    }

    Write-Output "=== 진상 멈춰 추론 서비스 ==="
    Write-Output "  실행 파일 : $실행파일"
    Write-Output "  모델      : $모델"
    Write-Output "  주소      : http://${호스트}:${포트}"
    # `$병렬개`로 쓰면 PowerShell이 변수 이름으로 삼키므로 중괄호로 끊는다.
    Write-Output "  컨텍스트  : $컨텍스트 (슬롯 ${병렬}개에 나뉜다 — 슬롯당 $([int]$컨텍스트 / [int]$병렬))"
    Write-Output ""

    # -ngl / --n-cpu-moe : 전문가 가중치는 RAM, 나머지는 GPU (ADR-0009 자원 배치)
    # -fa on             : 플래시 어텐션
    # --cache-type-k/v   : KV 캐시를 q8_0으로 눌러 VRAM을 아낀다
    # -np 2              : 슬롯 0 = 연기, 슬롯 1 = 채점 (ADR-0009 호출 규칙)
    # --jinja            : chat_template_kwargs로 추론 모드를 끄려면 필요하다
    # --host 127.0.0.1   : 외부에 노출하지 않는다 (ADR-0009)
    # --cors-origins     : 기본값이 '*'라 llama-server가 스스로 위험하다고 경고한다.
    #                      루프백 바인딩이 외부는 막지만, 시연 장비 브라우저에서 열린
    #                      아무 페이지나 127.0.0.1:8081로 교차 출처 요청을 보낼 수 있다.
    #                      브라우저는 `추론 서비스`를 직접 부르지 않으므로(슬라이스 #5)
    #                      좁혀 둔다. Spring은 서버에서 부르므로 Origin이 없어 영향이 없다.
    $인자 = @(
        '-m', $모델,
        '-ngl', $ngl,
        '--n-cpu-moe', $nCpuMoe,
        '-fa', 'on',
        '--cache-type-k', 'q8_0',
        '--cache-type-v', 'q8_0',
        '-c', $컨텍스트,
        '-np', $병렬,
        '--jinja',
        '--cors-origins', 'localhost',
        '--host', $호스트,
        '--port', $포트
    )

    & $실행파일 @인자
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
