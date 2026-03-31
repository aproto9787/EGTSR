# EGTSR - Execution-Grounded Task-State Runtime

## Project Identity
Claude Code 전용 장기 작업 상태 런타임. "기억"이 아니라 **작업 상태 통제**가 목적이다.
hook 이벤트와 tool 결과를 obligation-first / freshness-gated / SQLite-backed task state로 유지하고,
phase capsule로 컴파일하여 unsafe edit와 stale continuity illusion을 막는 로컬 런타임.

## Authoritative Documents

> **`MainDocs/` 디렉토리 내부 파일은 절대 수정하지 않는다.**
> 이 문서들은 프로젝트의 유일한 설계 권위(authority)다.

- **구현 순서의 유일한 기준**: `MainDocs/01_Implementation_Spine.md`
  - `02_*` 이후 문서는 구현 순서를 주장하지 않는다
  - 선행조건, 병렬 가능 여부, 완료 기준은 모두 `01`을 따른다
- **참고 명세 문서**: `MainDocs/02_*` ~ `MainDocs/11_*`
  - 현재 구현 중인 단계가 참조하는 문서만 펼쳐서 본다

### 문서 읽기 순서
1. `00_Project_Overview.md` — 전체 시스템 개요
2. `01_Implementation_Spine.md` — 구현 순서/단계 통제
3. 현재 단계가 참조하는 상세 문서 (`02_*` 이후)
4. `11_AI_Task_Packets_and_Backlog.md` — 파일 단위 작업 쪼개기

## Implementation Order (from 01_Implementation_Spine)

```
Step 00 Foundation Freeze
  -> Step 01 Domain State + SQLite
  -> Step 02 Hook Envelope + Session Bootstrap
  -> Step 03 Decision Capsule Compiler
  -> Step 04 Compile Audit + Prompt Gate
  -> Step 05 PostToolUse Ingest + Evidence Normalization
  -> Step 06 File-Touch Invalidation + Stale Quarantine
  -> Step 07 Resume Handshake + SessionEnd Snapshot
  -> Step 08 Verify Results + Attempt Families
  -> Step 09 MCP Skills + Local Operator UI        (병렬 가능: Step 10)
  -> Step 10 Observability + Recovery + Packaging   (병렬 가능: Step 09)
  -> Step 11 Benchmark Harness + Go/No-Go
```

- Step 00~08: **순차 구현** (병렬화 금지)
- Step 09~10: 병렬 허용
- Step 08 전 금지 작업: agent teams, Codex bridge, semantic search, web dashboard 등

## Immutable Decisions
- Claude Code 전용 (Codex는 optional artifact worker only)
- Python 3.12+
- SQLite single file
- obligation-first compile
- stale quarantine
- resume handshake
- MCP는 agent-facing 1순위 인터페이스

## Tech Stack
- **Language**: Python 3.12+
- **Storage**: SQLite single-file (`session.db`)
- **State dir**: `.egtsr/`
- **Interface**: Claude Code hooks (SessionStart / UserPromptSubmit / PostToolUse / SessionEnd)
- **Operator**: MCP skills + local read-only inspector UI

## Rules
- `MainDocs/` 수정 금지 — read-only authority
- 구현 순서 변경 금지 — `01_Implementation_Spine.md`가 유일한 기준
- JSON-only hook stdout
- Phase 1 correctness path: 네 개 hook + DB만으로 설명 가능해야 함
