# 07_Resume_Gate_Verify_and_Attempt_Families

> 이 문서는 `01_Implementation_Spine.md`의 Step 07, Step 08을 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Resume Gate, Verify Results, and Attempt Families

## 목적
resume/compact 이후 live recheck 없는 edit를 차단하고, verify 결과와 반복 실패 경로를 state로 다시 회수한다.

## 이 모듈이 시스템에서 담당하는 책임
- safe-resume enter rule
- required_rechecks 계산
- edit-intent gate
- SessionEnd snapshot / last_good_decision_capsule 저장
- resume_gate.json 저장
- verify result 기록
- obligation reopen / verify ladder 상태 반영
- attempt family clustering

## 선행 의존성
- `06_Tool_Ingest_Evidence_and_File_Touch_Invalidation.md`
- `05_Decision_Capsule_and_Compile_Audit.md`

## 후속 의존성
- operator inspect
- local UI
- benchmark harness
- ops/recovery

## 입력 / 출력
### 입력
- SessionStart(source=resume|compact|startup)
- repo head / dirty state
- invalidation tickets
- UserPromptSubmit prompt intent
- test/verify results
- patch/diff metadata

### 출력
- block/allow decision
- required_rechecks list
- `.egtsr/resume_gate.json`
- `.egtsr/last_good_decision_capsule.json`
- verify_results rows
- attempt_families rows
- reopened obligations / negative evidence lines

## 데이터 계약(contract)

### resume gate contract
```python
@dataclass(slots=True)
class ResumeGateState:
    session_id: str
    edit_blocked: bool
    reason: str | None
    required_rechecks: list[str]
    updated_at: str
```

### last good capsule contract
```python
@dataclass(slots=True)
class LastGoodDecisionCapsule:
    session_id: str
    compiled_at: str
    phase: Literal["decision"]
    token_estimate: int
    open_obligation_ids: list[str]
    blocking_rechecks: list[str]
    content: str
```

### verify result contract
```python
@dataclass(slots=True)
class VerifyResultRecord:
    id: str
    session_id: str
    phase: Literal["targeted","impacted_surface","broad_smoke"]
    outcome: Literal["pass","fail","flaky","unknown"]
    affected_obligation_ids: list[str]
    excerpt: str
    metadata_json: dict
```

### attempt family contract
```python
@dataclass(slots=True)
class AttemptFamilyRecord:
    id: str
    session_id: str
    obligation_id: str | None
    signature: str
    touched_scope_json: list[str]
    fail_count: int
    last_outcome: str
    summary: str | None
    metadata_json: dict
```

## 내부 서브컴포넌트
- safe-resume detector
- required recheck planner
- edit-intent gate
- snapshot writer
- verify result recorder
- obligation reopen service
- attempt family signature builder
- repeated failure summarizer

## 상태 전이 또는 처리 흐름
### resume handshake
1. SessionStart(source=resume|compact) 수신
2. repo head/dirty 확인
3. live stale tickets 확인
4. required_rechecks 계산
5. resume gate state 저장
6. decision capsule 재컴파일
7. UserPromptSubmit에서 edit-intent면 block

### verify result path
1. test outcome ingest
2. verify phase 결정
3. affected obligations 연결
4. pass/fail/flaky 기록
5. fail이면 obligation reopen 또는 addressed 유지
6. next verify ladder signal 생성

### attempt family path
1. failed patch or verify failure 발생
2. signature 계산
3. 기존 family merge or 신규 family 생성
4. fail_count 증가
5. decision capsule negative evidence에 요약 반영

## 구현 단계(step-by-step)
1. ResumeGateState 모델 작성
2. safe-resume detector 구현
3. required_rechecks 계산기 구현
4. edit-intent gate 연결
5. snapshot writer 구현
6. verify result recorder 구현
7. obligation reopen rule 구현
8. attempt family signature/merge 구현
9. repeated failure summary renderer 구현

## 실패 모드 / 예외 상황
- resume 이후 edit-intent를 allow해 unsafe edit 발생
- DB 손상 시 gate를 풀어버림
- compact source를 일반 startup으로 처리
- verify fail가 obligation reopen으로 이어지지 않음
- family signature가 너무 거칠어 unrelated failure가 합쳐짐
- family summary가 stale처럼 다시 live evidence로 섞임

## 테스트 전략
- resume edit blocked fixture
- resume read allowed fixture
- compact source behaves like resume fixture
- DB corruption safe-resume fallback fixture
- verify fail → obligation reopen fixture
- repeated failure clustering fixture
- latest failed family negative evidence fixture

## 완료 기준(Definition of Done)
- resume/compact 이후 edit-intent가 required rechecks 전에는 차단된다
- read/inspect/test prompt는 허용된다
- SessionEnd가 last_good_decision_capsule와 resume_gate를 저장한다
- verify fail가 obligation reopen 또는 regression signal로 기록된다
- repeated failed family가 decision capsule negative evidence에 반영된다

## 이후 모듈로 넘겨야 할 산출물
- resume gate service
- snapshot files
- verify recorder
- attempt family service
- recovery fixtures

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  services/
    resume_gate.py
    snapshot_writer.py
    verify_results.py
    obligation_reopen.py
    attempt_families.py
tests/
  fixtures/resume/
    resume_edit_blocked.json
    resume_read_allowed.json
    compact_start.json
    db_corruption_recovery.json
  fixtures/verify/
    targeted_fail_reopens_obligation.json
    repeated_family_merge.json
  test_resume_gate.py
  test_verify_results.py
  test_attempt_families.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
class ResumeGateService:
    def evaluate(self, session_id: str, source: str, prompt_intent: str | None = None) -> ResumeGateState: ...

class SnapshotWriter:
    def write_last_good_capsule(self, capsule: DecisionCapsuleV0) -> None: ...
    def write_resume_gate(self, state: ResumeGateState) -> None: ...

class VerifyResultsRecorder:
    def record(self, result: VerifyResultRecord) -> None: ...

class AttemptFamilyService:
    def register_failure(self, session_id: str, obligation_id: str | None, touched_files: list[str], outcome: str, excerpt: str) -> AttemptFamilyRecord: ...
```
