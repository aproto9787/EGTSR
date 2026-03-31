# 11_AI_Task_Packets_and_Backlog

> 이 문서는 `01_Implementation_Spine.md`의 모든 단계를 지원하는 작업 쪼개기 문서다.  
> 구현 순서의 authority는 `01`에 있다.  
> 이 문서는 **한 단계 안에서 AI에게 파일 단위로 일을 쪼개는 참고서**다.

## 모듈명
AI Task Packets and Backlog

## 목적
단계를 실제 파일 단위 작업으로 분해해 AI에게 순차 구현을 맡길 수 있게 한다.

## 이 모듈이 시스템에서 담당하는 책임
- Step별 세부 태스크 정의
- 태스크 간 의존성 표시
- 최소 테스트 단위 정의
- stub/mock 허용 범위 명시
- v0/v1/v2 확장선 명시

## 선행 의존성
- `01_Implementation_Spine.md`

## 후속 의존성
- 없음

## 태스크 패킷 템플릿
```md
# Ticket
[제목]

## Goal
이 티켓이 해결해야 하는 문제 한 줄.

## Dependencies
- ...

## In Scope
- ...

## Out of Scope
- ...

## Files
- ...

## Acceptance Criteria
- [ ] ...
- [ ] ...
- [ ] ...

## Tests
- unit:
- fixture:
- integration:
- regression:

## Failure Conditions
- ...
```

## 백로그 맵
```text
T001 Foundation constants / config / paths
T002 SQLite schema + repositories
T003 Hook envelope parser + response builder
T004 SessionStart bootstrap + repo inspector
T005 Decision capsule compiler v0
T006 Compile audit + prompt intent + UserPromptSubmit gate
T007 PostToolUse evidence normalizers
T008 File-touch invalidation + stale quarantine
T009 Resume gate + snapshots + SessionEnd
T010 Verify results recorder
T011 Attempt family clustering
T012 MCP inspect services + commands
T013 Local read-only inspector UI
T014 Observability + recovery CLI
T015 Packaging scaffold
T016 Benchmark harness + Go/No-Go
```

## 세부 구현 태스크 목록

### T001 — Foundation constants / config / paths
**Dependencies:** none  
**Files:** `constants.py`, `enums.py`, `paths.py`, `config.py`, `jsonio.py`

**Acceptance Criteria**
- [ ] 공통 enum/status가 문자열로 고정됨
- [ ] `.egtsr` 디렉터리 helper 제공
- [ ] JSON-only stdout helper 제공

**Tests**
- unit: enum serialization
- unit: path bootstrap
- unit: json stdout purity

**Stub/Mock**
- 없음

**v0 / v1 / v2**
- v0: defaults only
- v1: config file override
- v2: richer validation

---

### T002 — SQLite schema + repositories
**Dependencies:** T001  
**Files:** `db/schema.sql`, `db/migrations.py`, `repositories/*.py`, `db/uow.py`

**Acceptance Criteria**
- [ ] fresh DB migration 성공
- [ ] seed/load round-trip 성공
- [ ] transaction rollback 성공

**Tests**
- unit: CRUD
- integration: temp DB bootstrap
- regression: JSON field consistency

**Stub/Mock**
- sqlite temp file 사용, 외부 DB 없음

**v0 / v1 / v2**
- v0: tables + CRUD
- v1: indexes
- v2: maintenance/vacuum helpers

---

### T003 — Hook envelope parser + response builder
**Dependencies:** T002  
**Files:** `hooks/parser.py`, `hooks/envelopes.py`, `hooks/responses.py`

**Acceptance Criteria**
- [ ] 네 개 hook fixture parse 성공
- [ ] unknown field preserve
- [ ] allow/block JSON builder 동작

**Tests**
- fixture: official-shape JSON examples
- regression: missing optional fields

**Stub/Mock**
- raw fixture files로 대체

**v0 / v1 / v2**
- v0: 4 hook only
- v1: PostToolUseFailure
- v2: compact optimization hooks

---

### T004 — SessionStart bootstrap + repo inspector
**Dependencies:** T003  
**Files:** `services/repo_inspector.py`, `hooks/session_start.py`

**Acceptance Criteria**
- [ ] session create/load 가능
- [ ] repo head/dirty capture 가능
- [ ] compact source resume 취급

**Tests**
- integration: startup/resume/compact source
- regression: git failure fallback

**Stub/Mock**
- repo inspector는 subprocess mock 허용

**v0 / v1 / v2**
- v0: head/dirty only
- v1: branch capture
- v2: richer repo diagnostics

---

### T005 — Decision capsule compiler v0
**Dependencies:** T004  
**Files:** `compiler/*.py`

**Acceptance Criteria**
- [ ] open obligation 100% header 포함
- [ ] stale evidence exclusion
- [ ] negative evidence mandatory
- [ ] next-check derivation 동작

**Tests**
- fixture: reopened_regression_priority
- fixture: stale_excluded
- fixture: tight_budget_no_omission

**Stub/Mock**
- seeded DB state 사용

**v0 / v1 / v2**
- v0: decision only
- v1: edit/verify capsule
- v2: richer rendering

---

### T006 — Compile audit + prompt intent + gate
**Dependencies:** T005  
**Files:** `compiler/audit.py`, `compiler/prompt_intent.py`, `hooks/user_prompt_submit.py`

**Acceptance Criteria**
- [ ] hard-fail fixtures에서 block JSON 생성
- [ ] fail-open default 유지
- [ ] safe-resume generic block 예외 지원

**Tests**
- fixture: omitted obligation
- fixture: stale included
- fixture: unsupported confirmed assertion
- fixture: edit_intent_blocked

**Stub/Mock**
- compiler output fixture 사용 가능

**v0 / v1 / v2**
- v0: rule-based classifier
- v1: mixed prompt refinement
- v2: richer intent taxonomy

---

### T007 — PostToolUse evidence normalizers
**Dependencies:** T006  
**Files:** `ingest/*.py`, `hooks/post_tool_use.py`

**Acceptance Criteria**
- [ ] Read/Bash/Test/Diff normalize
- [ ] raw archive 저장
- [ ] changed_files 산출

**Tests**
- fixture: each tool event

**Stub/Mock**
- tool payload fixtures

**v0 / v1 / v2**
- v0: 4 tool types
- v1: failure ingest
- v2: more tools

---

### T008 — File-touch invalidation + stale quarantine
**Dependencies:** T007  
**Files:** `services/invalidation.py`

**Acceptance Criteria**
- [ ] related assertion stale mark
- [ ] stale active body exclusion
- [ ] verified obligation reopen candidate

**Tests**
- fixture: one changed file
- fixture: unrelated file no-op

**Stub/Mock**
- changed_files fixture

**v0 / v1 / v2**
- v0: file-level only
- v1: symbol hints
- v2: precise test-surface graph

---

### T009 — Resume gate + snapshots + SessionEnd
**Dependencies:** T008  
**Files:** `services/resume_gate.py`, `services/snapshot_writer.py`, `hooks/session_end.py`

**Acceptance Criteria**
- [ ] resume edit blocked
- [ ] resume read allowed
- [ ] last_good_decision_capsule/resume_gate 저장

**Tests**
- fixture: compact source behaves like resume
- regression: db corruption safe-resume fallback

**Stub/Mock**
- prompt intent classifier mock 가능

**v0 / v1 / v2**
- v0: edit block only
- v1: richer recheck planner
- v2: manual reviewed override flow

---

### T010 — Verify results recorder
**Dependencies:** T009  
**Files:** `services/verify_results.py`

**Acceptance Criteria**
- [ ] targeted/impacted/broad phase 저장
- [ ] fail가 obligation reopen과 연결

**Tests**
- fixture: targeted fail reopens obligation

**Stub/Mock**
- test output fixture

**v0 / v1 / v2**
- v0: record + reopen
- v1: flaky handling
- v2: richer verify ladder heuristics

---

### T011 — Attempt family clustering
**Dependencies:** T010  
**Files:** `services/attempt_families.py`

**Acceptance Criteria**
- [ ] repeated failed patch가 family로 merge
- [ ] latest family summary가 negative evidence에 반영

**Tests**
- fixture: repeated_family_merge

**Stub/Mock**
- touched_files/diff meta fixture

**v0 / v1 / v2**
- v0: signature by obligation+touched files
- v1: summary refinement
- v2: cooling-down heuristics

---

### T012 — MCP inspect services + commands
**Dependencies:** T011  
**Files:** `mcp/inspect.py`, `services/inspect.py`

**Acceptance Criteria**
- [ ] obligations/stale/capsule/resume_status 조회 가능

**Tests**
- unit: inspect service
- contract: MCP response payloads

**Stub/Mock**
- session seed DB

**v0 / v1 / v2**
- v0: core inspect only
- v1: diagnostics
- v2: benchmark viewer

---

### T013 — Local read-only inspector UI
**Dependencies:** T012  
**Files:** `ui/server.py`, `ui/routes.py`, `ui/view_models.py`

**Acceptance Criteria**
- [ ] summary/obligations/stale/capsule/verify 화면 존재
- [ ] write 없음

**Tests**
- API contract
- smoke test

**Stub/Mock**
- inspect service mock 가능

**v0 / v1 / v2**
- v0: local only
- v1: filtering
- v2: richer drill-down

---

### T014 — Observability + recovery CLI
**Dependencies:** T011  
**Files:** `ops/logging.py`, `ops/metrics.py`, `ops/health.py`, `ops/recovery_cli.py`

**Acceptance Criteria**
- [ ] structured logging
- [ ] metrics counters
- [ ] recovery doctor command

**Tests**
- logger schema
- recovery snapshot tests

**Stub/Mock**
- logger sink mock 가능

**v0 / v1 / v2**
- v0: local logs/counters
- v1: diagnostics integration
- v2: richer export

---

### T015 — Packaging scaffold
**Dependencies:** T013, T014  
**Files:** `scaffolds/standalone/*`, `scaffolds/claude-plugin/*`

**Acceptance Criteria**
- [ ] standalone scaffold 작성
- [ ] sample hooks/settings 제공
- [ ] install smoke test 존재

**Tests**
- scaffold install smoke

**Stub/Mock**
- UI optional

**v0 / v1 / v2**
- v0: standalone
- v1: plugin scaffold
- v2: improved installer

---

### T016 — Benchmark harness + Go/No-Go
**Dependencies:** T015  
**Files:** `benchmarks/*.py`

**Acceptance Criteria**
- [ ] forced split / stale injection / repeated failure 시나리오 실행
- [ ] same-budget report 생성
- [ ] continue/shrink/stop 판정 생성

**Tests**
- benchmark reproducibility
- report snapshot

**Stub/Mock**
- fixed scenario fixtures

**v0 / v1 / v2**
- v0: 3-way baseline
- v1: more scenarios
- v2: dashboard export
