# 06_Tool_Ingest_Evidence_and_File_Touch_Invalidation

> 이 문서는 `01_Implementation_Spine.md`의 Step 05, Step 06을 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Tool Ingest, Evidence Normalization, and File-Touch Invalidation

## 목적
successful PostToolUse payload를 evidence로 정규화해 저장하고, changed file 기반 stale quarantine를 적용한다.

## 이 모듈이 시스템에서 담당하는 책임
- Read/Bash/Test/Diff tool 결과 ingest
- raw archive와 active evidence 분리
- scope / polarity / excerpt tagging
- changed file extraction
- file-touch invalidation ticket 생성
- stale mark / reopen candidate 처리

## 선행 의존성
- `04_Hook_IO_Session_Bootstrap_and_Event_Normalization.md`
- `05_Decision_Capsule_and_Compile_Audit.md`

## 후속 의존성
- resume gate
- verify results
- operator inspect
- benchmark harness

## 입력 / 출력
### 입력
- PostToolUse envelope
- tool_input / tool_response
- current repo state
- current assertions / verify results / obligations

### 출력
- evidence rows
- changed_files list
- invalidation tickets
- stale assertions
- reopened obligations
- event log entries

## 데이터 계약(contract)

### supported tool kinds v0
- `Read` → `kind="read_span"`
- `Bash` → `kind="bash_output"`
- `Test` → `kind="test_output"`
- `Diff` → `kind="diff_meta"`

### evidence normalization contract
```python
@dataclass(slots=True)
class EvidenceRecord:
    id: str
    session_id: str
    kind: str
    source_tool: str
    path: str | None
    scope_kind: str | None
    scope_ref: str | None
    file_hash: str | None
    polarity: Literal["positive","negative"]
    excerpt: str
    metadata_json: dict
    created_at: str
```

### changed file contract
```python
@dataclass(slots=True)
class ChangedFilesDelta:
    files: list[str]
    symbols: list[str] | None = None  # v0 unused
```

### invalidation ticket contract
```python
@dataclass(slots=True)
class InvalidationTicket:
    id: str
    session_id: str
    subject_type: Literal["assertion","obligation","verify_result","capsule"]
    subject_id: str
    trigger_kind: Literal["file_touch","scope_change","test_surface","resume_recheck"]
    trigger_ref: str | None
    status: Literal["live","stale","revalidated","closed"]
    metadata_json: dict
```

## 내부 서브컴포넌트
- tool payload normalizers
- raw archive writer
- excerpt clipper
- changed file extractor
- evidence polarity tagger
- invalidation matcher
- stale quarantine policy engine

## 상태 전이 또는 처리 흐름
1. receive PostToolUse envelope
2. archive raw payload
3. normalize active evidence
4. extract changed files
5. write evidence rows
6. find impacted assertions / verify results / obligations
7. create invalidation tickets
8. mark stale / reopened
9. emit warn-only hook response

## 구현 단계(step-by-step)
1. tool별 normalizer 작성
2. raw vs active split 구현
3. changed file extractor 작성
4. evidence repository 연동
5. invalidation matcher 작성
6. assertion stale mark 로직 구현
7. reopened obligation 정책 구현
8. decision compiler exclusion test 추가

## 실패 모드 / 예외 상황
- raw verbose log가 active evidence로 그대로 들어감
- changed file 추출 실패
- unrelated file까지 wholesale stale 처리
- stale와 live state가 동시에 남음
- grep negative output가 polarity 잘못 태깅됨

## 테스트 전략
- read_event fixture
- bash_event fixture
- test_event fixture
- diff_event fixture
- one changed file → related assertion stale fixture
- unrelated file no-op fixture
- stale never shown as live regression test

## 완료 기준(Definition of Done)
- PostToolUse payload 4종이 evidence rows로 저장된다
- changed_files가 산출된다
- 관련 assertion/verify result가 stale mark 된다
- stale object가 다음 decision capsule의 live body에 제외된다
- verified obligation이 reopen candidate가 된다

## 이후 모듈로 넘겨야 할 산출물
- evidence normalizers
- changed file delta
- invalidation service
- stale/reopen policy
- tool fixtures

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  ingest/
    read_normalizer.py
    bash_normalizer.py
    test_normalizer.py
    diff_normalizer.py
    changed_files.py
    polarity.py
    excerpt.py
  services/
    evidence_ingest.py
    invalidation.py
tests/
  fixtures/tools/
    posttooluse_read.json
    posttooluse_bash.json
    posttooluse_test.json
    posttooluse_diff.json
  test_evidence_ingest.py
  test_file_touch_invalidation.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
class ToolEventNormalizer(Protocol):
    def normalize(self, envelope: HookEnvelope) -> list[EvidenceRecord]: ...
    def changed_files(self, envelope: HookEnvelope) -> list[str]: ...

class EvidenceIngestService:
    def ingest(self, envelope: HookEnvelope) -> "IngestResult": ...

@dataclass(slots=True)
class IngestResult:
    evidence_ids: list[str]
    changed_files: list[str]
    stale_assertion_ids: list[str]
    reopened_obligation_ids: list[str]

class FileTouchInvalidationService:
    def apply(self, session_id: str, changed_files: list[str]) -> "InvalidationResult": ...
```
