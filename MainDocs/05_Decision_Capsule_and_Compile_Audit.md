# 05_Decision_Capsule_and_Compile_Audit

> 이 문서는 `01_Implementation_Spine.md`의 Step 03, Step 04를 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Decision Capsule and Compile Audit

## 목적
현재 open obligations와 live evidence를 obligation-first capsule로 컴파일하고, omission/stale leak/unsupported confirmed assertion을 hard fail로 검증한다.

## 이 모듈이 시스템에서 담당하는 책임
- decision capsule v0 생성
- obligation ordering
- positive/negative/uncertainty pool selection
- next-check derivation
- token estimate / trimming
- compile audit hard-fail
- prompt gate decision input 생성

## 선행 의존성
- `03_Domain_State_and_SQLite_Model.md`
- `04_Hook_IO_Session_Bootstrap_and_Event_Normalization.md`

## 후속 의존성
- prompt gate
- resume gate
- operator inspect
- benchmark harness

## 입력 / 출력
### 입력
- open obligations
- evidence rows
- assertion rows
- invalidation tickets
- attempt families
- token budget

### 출력
- DecisionCapsuleV0
- audit report JSON
- allow/block recommendation payload

## 데이터 계약(contract)

### compiler input
```python
@dataclass(slots=True)
class DecisionCompilerInput:
    session_id: str
    cwd: str
    user_prompt: str
    token_budget: int
    open_obligations: list[Obligation]
    evidence: list[Evidence]
    assertions: list[Assertion]
    invalidation_tickets: list[InvalidationTicket]
    attempt_families: list[AttemptFamily]
```

### compiler output
```python
@dataclass(slots=True)
class ObligationBlock:
    obligation_id: str
    priority: str
    title: str
    state: str
    positive_items: list[str]
    negative_items: list[str]
    uncertainty_items: list[str]
    suggested_next_check: str

@dataclass(slots=True)
class DecisionCapsuleV0:
    phase: Literal["decision"]
    header_obligations: list[str]
    warnings: list[str]
    obligation_blocks: list[ObligationBlock]
    next_checks: list[str]
    token_estimate: int
    audit_inputs: dict
    rendered_text: str
```

### audit report
```python
@dataclass(slots=True)
class CapsuleAuditReport:
    passed: bool
    hard_fail_reasons: list[str]
    soft_warnings: list[str]
    rendered_obligation_ids: list[str]
    open_obligation_ids: list[str]
    stale_evidence_ids_seen: list[str]
    unsupported_confirmed_assertion_ids: list[str]
    token_estimate: int
    budget: int
```

## 내부 서브컴포넌트
- obligation ordering engine
- evidence pool builder
- assertion admission checker
- next-check derivation engine
- token estimator
- capsule renderer
- audit engine
- prompt intent classifier v0

## 상태 전이 또는 처리 흐름
1. load active state
2. sort obligations
3. build warnings section
4. build per-obligation pools
5. derive next checks
6. trim to budget
7. render capsule text
8. compute audit inputs
9. audit pass/fail
10. emit allow/block recommendation

## 구현 단계(step-by-step)
1. DecisionCompilerInput/Output datamodel 작성
2. obligation ordering 구현
3. positive/negative/uncertainty pool selectors 구현
4. assertion admission rule 구현
5. next-check derivation 구현
6. token estimator 구현
7. renderer 구현
8. audit engine 구현
9. prompt intent classifier v0 구현
10. UserPromptSubmit handler 연결

## 실패 모드 / 예외 상황
- open obligation omission
- stale evidence inclusion
- unsupported confirmed assertion inclusion
- negative evidence slot 누락
- token trimming이 header를 잘라버림
- mixed prompt를 edit-intent로 잘못 판정하거나 반대로 놓침

## 테스트 전략
- reopened regression priority fixture
- stale evidence excluded fixture
- negative evidence required fixture
- no-live-evidence → READ_REQUIRED fixture
- recent failed family → INVESTIGATE_ALT_PATH fixture
- unsupported confirmed assertion blocked fixture
- tight-budget no omission fixture
- audit hard-fail fixtures
- prompt classifier fixture set

## 완료 기준(Definition of Done)
- reopened regression obligation이 항상 상단에 배치된다
- 모든 active obligation에 negative evidence 또는 placeholder가 있다
- stale evidence가 live body에 포함되지 않는다
- supported 조건 없는 confirmed assertion이 live body에 없다
- audit fail이 machine-readable JSON으로 저장된다
- UserPromptSubmit block path가 audit 결과를 사용한다

## 이후 모듈로 넘겨야 할 산출물
- decision compiler
- audit engine
- prompt intent classifier
- rendered capsule format
- compiler fixtures

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  compiler/
    decision_models.py
    decision_compiler.py
    ordering.py
    pools.py
    next_checks.py
    renderer.py
    token_estimator.py
    audit.py
    prompt_intent.py
tests/
  fixtures/compiler/
    reopened_regression_priority.json
    stale_evidence_excluded.json
    negative_evidence_required.json
    no_live_evidence_read_required.json
    recent_failed_family_alt_path.json
    unsupported_confirmed_assertion_blocked.json
    tight_budget_no_omission.json
  test_decision_compiler.py
  test_compile_audit.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
class DecisionCapsuleCompiler:
    def compile(self, data: DecisionCompilerInput) -> DecisionCapsuleV0: ...

class CapsuleAuditEngine:
    def audit(self, capsule: DecisionCapsuleV0) -> CapsuleAuditReport: ...

class PromptIntentClassifier:
    def classify(self, prompt: str) -> Literal["read","inspect","edit","test","mixed"]: ...

def derive_next_check(
    obligation: Obligation,
    positive: list[str],
    negative: list[str],
    uncertainty: list[str],
    has_recent_failed_family: bool,
    has_unresolved_stale_ticket: bool,
) -> str: ...
```
