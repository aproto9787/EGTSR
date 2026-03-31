# 01_Implementation_Spine

> 이 문서는 EGTSR 구현의 **유일한 실행 기준 문서**다.  
> 구현 순서, 선행조건, 병렬 가능 여부, 산출물, 완료 기준은 이 문서를 따른다.  
> `02_*` 이후 문서는 이 단계들을 지원하는 상세 참고 문서다.

## 1. 전체 구현 단계 개요
구현은 아래 순서를 고정한다.

```text
Step 00 Foundation Freeze
  -> Step 01 Domain State + SQLite
  -> Step 02 Hook Envelope + Session Bootstrap
  -> Step 03 Decision Capsule Compiler
  -> Step 04 Compile Audit + Prompt Gate
  -> Step 05 PostToolUse Ingest + Evidence Normalization
  -> Step 06 File-Touch Invalidation + Stale Quarantine
  -> Step 07 Resume Handshake + SessionEnd Snapshot
  -> Step 08 Verify Results + Attempt Families
  -> Step 09 MCP Skills + Local Operator UI
  -> Step 10 Observability + Recovery + Release Packaging
  -> Step 11 Benchmark Harness + Go/No-Go
```

## 2. 의존성 그래프

```text
Foundation
  └─ Domain/SQLite
      └─ Hook Envelope / Session Bootstrap
          └─ Decision Capsule Compiler
              └─ Compile Audit / Prompt Gate
                  └─ PostToolUse Ingest
                      └─ File-Touch Invalidation
                          └─ Resume Handshake / Snapshot
                              └─ Verify Results / Attempt Families
                                  ├─ MCP Skills / Local UI
                                  └─ Observability / Recovery / Packaging
                                          └─ Benchmark Harness / Go-NoGo
```

## 3. 병렬화 규칙
- Step 00~08은 **순차 구현**이 기본이다.
- 병렬화는 Step 08 이후에만 허용한다.
- 허용되는 병렬화:
  - `09 MCP Skills + Local UI`
  - `10 Observability + Recovery + Release Packaging`
- 금지되는 병렬화:
  - Step 03 이전에 UI 착수
  - Step 04 이전에 prompt gate / block JSON 착수
  - Step 05 이전에 invalidation 착수
  - Step 07 이전에 compact 관련 최적화 착수
  - Step 11 이전에 “성과 홍보용” 데모 정리 착수

## 4. 지금 손대면 안 되는 후순위 작업
다음은 Step 08 전 금지한다.
- PreCompact/PostCompact correctness 의존
- agent teams
- Codex bridge
- semantic search
- learned ranking / weight tuning
- web dashboard
- symbol-level invalidation
- autonomous PR/worker orchestration

---

## Step 00. Foundation Freeze

### 왜 지금 이걸 먼저 하는가
- 프로젝트의 변경 불가 결정을 먼저 고정하지 않으면 뒤 단계에서 다시 갈아엎게 된다.
- state authority, non-goals, enum, 파일 구조, JSON contract naming이 흔들리면 이후 테스트 fixture가 전부 깨진다.

### 목표
- 변경 불가 결정, enum, 공통 파일 구조, naming rule, error policy를 고정한다.
- Phase 1 correctness path를 compact hooks와 분리한다.

### 선행 조건
- 없음

### 참고 문서
- `02_Foundation_and_Conventions.md`

### 구현 항목
- 공통 package layout 결정
- dataclass / enum naming rule 결정
- JSON-only hook stdout 규칙 결정
- Phase 1 allowed hooks 확정
- `.egtsr/` 디렉터리 표준 경로 확정
- fixture 디렉터리 표준 경로 확정

### 산출물
- package skeleton
- enums/constants module
- config schema skeleton
- repository/test fixture directory skeleton

### 완료 기준
- 패키지 구조가 고정되어 이후 문서의 파일 경로 참조가 흔들리지 않는다.
- Phase 1 correctness path가 네 개 hook + DB만으로 설명 가능하다.

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- DB 테이블 구현
- hook business logic
- capsule compiler

---

## Step 01. Domain State + SQLite

### 왜 지금 이걸 먼저 하는가
- 모든 후속 단계가 obligations/evidence/assertions/...을 읽고 쓴다.
- 저장 모델이 없으면 compiler, invalidation, resume gate를 테스트할 수 없다.

### 목표
- 단일 SQLite DB와 typed repository layer를 만든다.
- append/update 규칙과 상태 enum을 고정한다.

### 선행 조건
- Step 00 완료

### 참고 문서
- `03_Domain_State_and_SQLite_Model.md`

### 구현 항목
- migration runner
- schema DDL
- repository CRUD
- transaction wrapper
- fixture seed loader
- repo_state/session snapshot API

### 산출물
- `session.db` migration
- repository interfaces and implementations
- state dataclasses / pydantic models
- temp-db integration tests

### 완료 기준
- fresh DB migration 성공
- fixture seed 후 load/round-trip 가능
- session snapshot save/load 가능
- enum/status 전이가 테스트로 고정됨

### 병렬 가능 작업
- 매우 제한적: fixture data builder 정도만 허용

### 지금 하지 말 것
- hook parser
- capsule compiler
- UI

---

## Step 02. Hook Envelope + Session Bootstrap

### 왜 지금 이걸 먼저 하는가
- 모든 상태 변경은 hook 이벤트에서 들어온다.
- raw input shape가 잠기지 않으면 이후 logic이 fixture 없이 흔들린다.

### 목표
- SessionStart/UserPromptSubmit/PostToolUse/SessionEnd raw stdin을 normalized envelope로 바꾼다.
- SessionStart bootstrap을 구현한다.

### 선행 조건
- Step 01 완료

### 참고 문서
- `04_Hook_IO_Session_Bootstrap_and_Event_Normalization.md`

### 구현 항목
- raw JSON parser
- unknown/optional field tolerant adapter
- normalized envelope dataclass
- repo head / dirty inspector
- session create/load logic
- source=`startup|resume|compact` normalization

### 산출물
- hook adapter module
- SessionStart bootstrap service
- four-hook fixture set
- parser unit tests

### 완료 기준
- four-hook fixture JSON parse 성공
- unknown field 보존
- SessionStart에서 session create/load + repo state inspect 가능
- compact source를 resume와 동일하게 인식

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- prompt block
- capsule compile
- evidence ingest

---

## Step 03. Decision Capsule Compiler

### 왜 지금 이걸 먼저 하는가
- EGTSR의 핵심 가치가 decision capsule omission safety에 있다.
- 이 단계가 없으면 runtime은 그냥 상태 저장소에 그친다.

### 목표
- deterministic rule-based decision capsule compiler v0를 완성한다.
- open obligation 100% 포함, stale exclusion, negative evidence inclusion을 보장한다.

### 선행 조건
- Step 01 완료
- Step 02 완료

### 참고 문서
- `05_Decision_Capsule_and_Compile_Audit.md`
- `11_AI_Task_Packets_and_Backlog.md`

### 구현 항목
- obligation ordering
- evidence pool selection
- assertion admission rule
- negative evidence placeholder rule
- next-check derivation
- token estimate / trimming

### 산출물
- decision capsule datamodel
- compiler implementation
- compiler fixtures
- render helper

### 완료 기준
- reopened regression이 항상 header 최상단으로 온다
- stale evidence가 live body에 들어가지 않는다
- negative evidence slot이 모든 active obligation에 존재한다
- tight budget에서도 header omission이 없다

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- edit capsule
- verify capsule
- learned ranking

---

## Step 04. Compile Audit + Prompt Gate

### 왜 지금 이걸 먼저 하는가
- compiler만 있으면 “그럴듯하게 틀리는” 상태가 남는다.
- audit가 있어야 omission/stale leak/unsupported confirmed assertion을 hard fail로 만들 수 있다.

### 목표
- compile audit v0와 UserPromptSubmit allow/block 경로를 연결한다.

### 선행 조건
- Step 03 완료

### 참고 문서
- `05_Decision_Capsule_and_Compile_Audit.md`
- `04_Hook_IO_Session_Bootstrap_and_Event_Normalization.md`

### 구현 항목
- audit engine
- audit report JSON
- prompt intent classifier v0
- UserPromptSubmit handler
- allow JSON / block JSON response builder

### 산출물
- audit engine
- prompt gate service
- blocked fixture set
- generic safe-resume fallback block path

### 완료 기준
- hard-fail fixture에서 block JSON 생성
- audit report가 machine-readable JSON으로 저장됨
- compiler crash 시 fail-open, 단 safe-resume generic block 예외만 남음

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- PostToolUse business logic
- invalidation
- UI

---

## Step 05. PostToolUse Ingest + Evidence Normalization

### 왜 지금 이걸 먼저 하는가
- decision capsule이 살아 있으려면 실제 tool 결과가 state로 들어와야 한다.
- invalidation과 resume gate도 changed_files/evidence가 있어야 의미가 생긴다.

### 목표
- PostToolUse 성공 경로에서 Read/Bash/Test/Diff 결과를 evidence로 정규화해 저장한다.

### 선행 조건
- Step 04 완료

### 참고 문서
- `06_Tool_Ingest_Evidence_and_File_Touch_Invalidation.md`

### 구현 항목
- raw archive 저장
- active excerpt extraction
- evidence kind/source_tool/scope/polarity tagging
- changed file 추출
- event log 기록

### 산출물
- ingest normalizer
- evidence repository wiring
- tool payload fixtures
- changed-files extractor

### 완료 기준
- fixture payload 4종이 모두 evidence rows로 저장됨
- raw verbose log는 archive로만 저장됨
- changed_files가 안정적으로 추출됨
- tool 결과 이후 state delta가 발생함

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- failed tool ingest
- scope graph refinement

---

## Step 06. File-Touch Invalidation + Stale Quarantine

### 왜 지금 이걸 먼저 하는가
- evidence를 쌓기만 하면 memory product가 된다.
- file touch 이후 stale quarantine가 걸려야 runtime이 계속 믿을 수 있는 상태를 유지한다.

### 목표
- changed file 기반 invalidation v0를 구현한다.
- stale object를 삭제하지 않고 quarantine한다.

### 선행 조건
- Step 05 완료

### 참고 문서
- `06_Tool_Ingest_Evidence_and_File_Touch_Invalidation.md`

### 구현 항목
- changed file → impacted assertions / verify_results / obligations 찾기
- invalidation ticket 생성/갱신
- assertion stale mark
- verified obligation reopen candidate 처리
- decision capsule active body exclusion 연결

### 산출물
- invalidation service
- stale quarantine policy
- reopen rules
- regression tests

### 완료 기준
- changed file fixture에서 관련 assertion이 stale 처리된다
- stale object가 decision capsule active body에 다시 나타나지 않는다
- 관련 verified obligation이 reopened로 이동 가능하다

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- symbol-level invalidation
- test-surface graph
- compact 최적화

---

## Step 07. Resume Handshake + SessionEnd Snapshot

### 왜 지금 이걸 먼저 하는가
- 장기 작업 품질 하락의 핵심은 resume 이후 무근거 edit다.
- safe-resume gate가 없으면 compact/resume 뒤에 state drift가 폭발한다.

### 목표
- resume / compact / dirty repo / stale ticket 상태에서 live recheck 전 edit를 막는다.
- SessionEnd snapshot과 보조 artifact를 저장한다.

### 선행 조건
- Step 06 완료

### 참고 문서
- `07_Resume_Gate_Verify_and_Attempt_Families.md`
- `09_Config_Observability_Ops_and_Recovery.md`

### 구현 항목
- safe-resume mode enter rules
- required_rechecks 계산
- edit-intent block logic
- last_good_decision_capsule.json 저장
- resume_gate.json 저장
- SessionEnd final snapshot

### 산출물
- resume gate service
- snapshot writer
- resume fixtures
- recovery path tests

### 완료 기준
- resume edit-intent prompt가 차단된다
- read/inspect/test prompt는 허용된다
- compact source start도 resume와 동일한 handshake를 탄다
- DB 손상 시 safe-resume fallback이 동작한다

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- manual override UI
- compact hooks dependence

---

## Step 08. Verify Results + Attempt Families

### 왜 지금 이걸 먼저 하는가
- edit 이후의 결과를 state로 다시 회수해야 obligation reopen이 가능해진다.
- 반복 실패 경로를 묶어야 Claude가 같은 패치를 반복하지 않는다.

### 목표
- verify results recorder v0와 attempt family clustering v0를 구현한다.

### 선행 조건
- Step 07 완료

### 참고 문서
- `07_Resume_Gate_Verify_and_Attempt_Families.md`

### 구현 항목
- targeted / impacted_surface / broad_smoke verify phase model
- verify result persistence
- obligation reopen/update transition
- attempt family signature generation
- fail count / latest summary recording
- decision capsule negative evidence integration

### 산출물
- verify recorder
- attempt family service
- verify ladder tests
- repeated-failure fixtures

### 완료 기준
- failing verify가 obligation reopen으로 이어진다
- recent failed family가 decision capsule negative evidence에 반영된다
- repeated patch family benchmark용 CSV/JSON 추출이 가능하다

### 병렬 가능 작업
- Step 09, Step 10

### 지금 하지 말 것
- subagent verifier
- adaptive ranking

---

## Step 09. MCP Skills + Local Operator UI

### 왜 지금 이걸 이 시점에 하는가
- core semantics가 잠기기 전 UI를 붙이면 화면이 authority를 오염시킨다.
- Step 08 이후면 read-only inspection과 operator commands를 안전하게 추가할 수 있다.

### 목표
- MCP inspect skills와 local read-only inspector UI를 만든다.

### 선행 조건
- Step 08 완료

### 참고 문서
- `08_MCP_Skills_Operator_UI_and_Commands.md`

### 구현 항목
- `inspect_obligations`
- `inspect_stale`
- `inspect_capsule`
- `resume_status`
- read-only local inspector
- basic recovery command surface

### 산출물
- MCP tool handlers
- local UI skeleton
- API adapters / response DTOs

### 완료 기준
- operator가 shell 없이 open obligations / stale tickets / last capsule을 읽을 수 있다
- UI는 state mutation을 하지 않는다
- unsafe manual unblock 경로가 없다

### 병렬 가능 작업
- Step 10

### 지금 하지 말 것
- multi-user UI
- write-enabled admin panel

---

## Step 10. Observability + Recovery + Release Packaging

### 왜 지금 이걸 이 시점에 하는가
- core path가 잠기기 전 로그/알림/패키징을 설계하면 interface churn만 커진다.
- Step 08 이후에는 error taxonomy와 state transitions가 충분히 드러난다.

### 목표
- runtime observability, recovery CLI, minimal package/release 구조를 만든다.

### 선행 조건
- Step 08 완료

### 참고 문서
- `09_Config_Observability_Ops_and_Recovery.md`
- `10_Deployment_Release_and_GoNoGo.md`

### 구현 항목
- structured logging
- metrics counters
- debug artifact paths
- recovery CLI
- package manifest / installer skeleton
- sample `.claude/hooks.json` and plugin manifest

### 산출물
- config schema
- log/metric emitters
- recovery commands
- packaging scaffold

### 완료 기준
- block/fail-open/stale/reopen/recovery events가 로그에서 식별된다
- operator가 corrupted DB / safe-resume 상태를 진단할 수 있다
- demo 가능한 설치 scaffold가 있다

### 병렬 가능 작업
- Step 09

### 지금 하지 말 것
- enterprise deployment
- hosted service packaging

---

## Step 11. Benchmark Harness + Go/No-Go

### 왜 지금 이걸 마지막에 하는가
- 앞 단계 semantics가 잠기기 전 평가는 숫자만 남고 의미가 없다.
- Go/No-Go는 implementation-complete 기준에서만 판정해야 한다.

### 목표
- raw transcript / naive summary / EGTSR 3-way baseline harness와 Go/No-Go 판정을 만든다.

### 선행 조건
- Step 09 완료
- Step 10 완료

### 참고 문서
- `10_Deployment_Release_and_GoNoGo.md`
- `11_AI_Task_Packets_and_Backlog.md`

### 구현 항목
- forced split scenario
- stale injection scenario
- repeated failure scenario
- same-budget comparison harness
- report generator
- continue/shrink/stop rubric

### 산출물
- benchmark harness
- CSV/JSON report
- demo scripts
- Go/No-Go memo

### 완료 기준
- one forced split demo, one stale injection demo, one repeated-failure demo가 재현 가능하다
- same-budget evaluation report가 생성된다
- continue / shrink / stop 판정이 문서화된다

### 병렬 가능 작업
- 없음

### 지금 하지 말 것
- marketing deck
- feature expansion pitch

---

## 5. 통합 시작 시점
다음 조건이 모두 만족되면 통합을 시작한다.
- Step 07 완료: resume safety가 동작
- Step 08 완료: verify/attempt signal이 state에 닿음
- Step 09 또는 Step 10 중 하나 완료: operator가 문제를 읽을 수 있음

## 6. 릴리즈 직전 체크포인트
- open obligation omission hard fail이 실제 block로 연결되는가
- stale object가 live capsule에 포함되지 않는가
- resume 후 edit-intent block가 일관되게 작동하는가
- DB 손상 시 safe-resume fallback이 있는가
- changed file 이후 verified obligation reopen이 가능한가
- repeated failed family가 negative evidence로 다시 노출되는가
- package scaffold로 local install/demo가 가능한가

## 7. 단계별 산출물 묶음
- Step 00~02: foundation bundle
- Step 03~04: decision path bundle
- Step 05~06: ingest + invalidation bundle
- Step 07~08: resume + verify bundle
- Step 09~10: operator + ops bundle
- Step 11: evaluation bundle
