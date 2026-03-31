# 10_Deployment_Release_and_GoNoGo

> 이 문서는 `01_Implementation_Spine.md`의 Step 10, Step 11을 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Deployment, Release, and Go/No-Go

## 목적
local install/demo가 가능한 패키징 구조와 benchmark-based Go/No-Go 판정을 제공한다.

## 이 모듈이 시스템에서 담당하는 책임
- standalone runtime scaffold
- Claude hook config / plugin scaffold
- minimal package manifest
- benchmark harness
- same-budget report
- continue / shrink / stop 판정

## 선행 의존성
- `08_MCP_Skills_Operator_UI_and_Commands.md`
- `09_Config_Observability_Ops_and_Recovery.md`

## 후속 의존성
- 없음 (최종 단계)

## 입력 / 출력
### 입력
- packaged runtime
- fixture scenarios
- baseline runs (raw / summary / EGTSR)

### 출력
- installable scaffold
- benchmark reports
- demo scripts
- Go/No-Go memo

## 데이터 계약(contract)

### required packaged artifacts
```text
.egtsr/session.db
.egtsr/runtime.log
.egtsr/last_good_decision_capsule.json
.egtsr/resume_gate.json
.claude/hooks.json
(optional) .claude-plugin/plugin.json
```

### benchmark scenario set
- forced split
- stale injection
- repeated failed patch family
- same-budget comparison

### Go / No-Go rubric
- **Continue**: obligation omission 없음, stale leak 없음, resume block 안정, baseline 대비 continuity 개선
- **Shrink**: core safety는 되지만 overhead/quality uplift 미약
- **Stop**: omission/stale leak/resume safety 중 하나라도 안정적으로 해결 못함

## 내부 서브컴포넌트
- package scaffold generator
- sample hooks.json writer
- benchmark harness runner
- report generator
- demo script runner

## 상태 전이 또는 처리 흐름
1. install scaffold 생성
2. local runtime smoke run
3. benchmark scenarios 실행
4. raw / summary / EGTSR 비교
5. report 생성
6. continue/shrink/stop 판정

## 구현 단계(step-by-step)
1. standalone scaffold 작성
2. sample hooks.json / settings.json 작성
3. package install smoke test 작성
4. benchmark scenario fixtures 정리
5. harness runner 구현
6. report generator 구현
7. Go/No-Go memo template 작성

## 실패 모드 / 예외 상황
- install scaffold와 실제 runtime file path 불일치
- benchmark가 same-budget가 아니라 unfair comparison
- demo만 되고 재현이 안 됨
- report가 qualitative rhetoric만 있고 machine output 없음

## 테스트 전략
- install smoke tests
- hooks config path tests
- benchmark reproducibility tests
- report snapshot tests

## 완료 기준(Definition of Done)
- local install/demo가 가능하다
- forced split / stale injection / repeated failure 시나리오가 재현 가능하다
- same-budget comparison report가 생성된다
- continue/shrink/stop 판정 문서가 나온다

## 이후 모듈로 넘겨야 할 산출물
- packaged scaffold
- benchmark harness
- Go/No-Go report

## 가능하면 폴더 구조 / 파일 구조
```text
scaffolds/
  standalone/
    .claude/
      hooks.json
      settings.json
  claude-plugin/
    .claude-plugin/
      plugin.json
egtsr_runtime/
  benchmarks/
    scenarios.py
    runner.py
    reports.py
tests/
  test_scaffold_install.py
  test_benchmark_runner.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
class ScaffoldGenerator:
    def write_standalone(self, repo_root: str) -> None: ...
    def write_plugin(self, repo_root: str) -> None: ...

class BenchmarkRunner:
    def run(self, scenario_name: str) -> dict: ...

class GoNoGoEvaluator:
    def evaluate(self, report_paths: list[str]) -> Literal["continue","shrink","stop"]: ...
```
