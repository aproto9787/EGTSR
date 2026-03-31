# 09_Config_Observability_Ops_and_Recovery

> 이 문서는 `01_Implementation_Spine.md`의 Step 07, Step 10을 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Config, Observability, Ops, and Recovery

## 목적
runtime 설정, structured logging, metrics, recovery path, debug artifacts를 독립 모듈로 정의한다.

## 이 모듈이 시스템에서 담당하는 책임
- 환경설정 로드
- secrets/paths 정리
- structured logging
- metrics counters
- debug artifact 저장
- recovery CLI
- 운영 체크리스트 제공

## 선행 의존성
- `02_Foundation_and_Conventions.md`
- `07_Resume_Gate_Verify_and_Attempt_Families.md`

## 후속 의존성
- packaging
- local UI diagnostics
- benchmark harness

## 입력 / 출력
### 입력
- env vars
- config file
- runtime events
- DB/artifact health

### 출력
- runtime config object
- logs
- metrics
- recovery CLI output
- ops checklists

## 데이터 계약(contract)

### runtime config
```python
@dataclass(slots=True)
class RuntimeConfig:
    repo_root: str
    egtsr_dir: str
    db_path: str
    max_decision_tokens: int = 900
    enable_compact_hooks: bool = False
    log_level: str = "INFO"
    metrics_enabled: bool = True
```

### event log schema
```python
@dataclass(slots=True)
class RuntimeLogEvent:
    ts: str
    level: str
    event_type: str
    session_id: str | None
    details: dict
```

### recommended counters
- `hook_session_start_total`
- `hook_prompt_submit_total`
- `hook_post_tool_use_total`
- `hook_fail_open_total`
- `compile_audit_fail_total`
- `resume_edit_block_total`
- `stale_ticket_total`
- `obligation_reopened_total`
- `verify_fail_total`
- `attempt_family_created_total`

## 내부 서브컴포넌트
- config loader
- structured logger
- metrics emitter
- artifact health checker
- recovery CLI
- ops checklist renderer

## 상태 전이 또는 처리 흐름
1. load config
2. initialize logger/metrics
3. runtime emits events during hook handling
4. health checker inspects DB/artifacts
5. recovery CLI prints diagnosis and safe actions

## 구현 단계(step-by-step)
1. config dataclass + env loader 작성
2. logger 구현
3. metrics emitter 구현
4. artifact health checker 구현
5. recovery CLI 작성
6. operator checklist 문구 추가
7. fail-open logging integration 추가

## 실패 모드 / 예외 상황
- config default가 문서와 불일치
- fail-open이 조용히 지나가 root cause 추적 불가
- metrics가 business logic에 결합돼 runtime 흐름을 깨뜨림
- recovery CLI가 unsafe “manual unblock”를 제공
- secrets/paths가 로그에 노출

## 테스트 전략
- config load tests
- logger schema tests
- metrics emission tests
- health checker tests
- recovery CLI snapshot tests

## 완료 기준(Definition of Done)
- runtime config가 env/file에서 안정적으로 로드된다
- fail-open/block/stale/reopen/verify_fail이 구조화 로그에 남는다
- metrics counter가 노출된다
- recovery CLI가 DB/artifact health를 진단한다
- unsafe unblock 명령이 없다

## 이후 모듈로 넘겨야 할 산출물
- config module
- logging/metrics module
- diagnostics and recovery services
- ops checklist

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  ops/
    config_loader.py
    logging.py
    metrics.py
    health.py
    recovery_cli.py
tests/
  test_config_loader.py
  test_logging_schema.py
  test_metrics.py
  test_recovery_cli.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
def load_runtime_config(repo_root: str) -> RuntimeConfig: ...
def log_event(event: RuntimeLogEvent) -> None: ...
def incr_counter(name: str, value: int = 1, labels: dict | None = None) -> None: ...

class HealthChecker:
    def check(self, repo_root: str) -> dict: ...

class RecoveryCLI:
    def doctor(self, repo_root: str) -> int: ...
```
