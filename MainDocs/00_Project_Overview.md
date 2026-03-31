# 00_Project_Overview

## 프로젝트 목적
EGTSR(Execution-Grounded Task-State Runtime)을 **Claude Code 전용 장기 작업 상태 런타임**으로 구현한다. 목표는 “기억”이 아니라 **작업 상태 통제**다. 런타임은 open obligation, live evidence, stale quarantine, resume gate, phase capsule을 관리해 긴 세션/compact/resume 이후에도 해결 경로가 흐트러지지 않게 만든다.

## 시스템 한 줄 정의
Claude Code의 hook 이벤트와 tool 결과를 **obligation-first / freshness-gated / SQLite-backed task state**로 유지하고, 그 상태를 phase capsule로 컴파일하여 unsafe edit와 stale continuity illusion을 막는 로컬 런타임.

## 전체 시스템 개요
시스템은 아래 다섯 축으로 구성된다.

1. **State Core**
   - obligations, evidence, assertions, invalidation tickets, verify results, attempt families, capsules, sessions
   - SQLite single-file
2. **Hook Runtime**
   - SessionStart / UserPromptSubmit / PostToolUse / SessionEnd
   - raw stdin JSON → normalized envelope → state mutation / capsule compile
3. **Safety Layer**
   - compile audit
   - stale quarantine
   - safe-resume handshake
   - edit-intent gate
4. **Operator Layer**
   - MCP inspect commands
   - local read-only inspector UI
   - debug / recovery CLI
5. **Release / Evaluation**
   - baseline harness
   - forced split / stale injection evaluation
   - Go / No-Go gate

## 문서 세트 사용법
- **평소 구현 순서와 단계 통제는 `01_Implementation_Spine.md`만 본다.**
- 세부 모델, 스키마, 인터페이스, 테스트는 해당 상세 문서를 펼쳐서 구현한다.
- `02_*` 이후 문서는 구현 순서를 새로 주장하지 않는다. 구현 순서의 authority는 `01` 하나다.

## Authoritative 문서
- 구현 순서 / 선행조건 / 병렬 가능 여부 / 단계 완료 기준: **`01_Implementation_Spine.md`**
- 그 외 문서는 모두 **참고 명세 문서**다.

## 구현자가 읽는 권장 순서
1. `00_Project_Overview.md`
2. `01_Implementation_Spine.md`
3. 현재 구현 중인 단계가 참조하는 `02_*` 이후 상세 문서
4. `11_AI_Task_Packets_and_Backlog.md`로 파일 단위 작업 쪼개기

## 변경 불가 결정
- Claude Code 전용
- Codex는 기본 OFF, optional artifact worker only
- agent teams 기본 OFF
- authoritative state는 Claude lead만
- obligation-first compile
- stale quarantine
- resume handshake
- SQLite single file
- Python 3.12+
- MCP는 agent-facing 1순위 인터페이스
