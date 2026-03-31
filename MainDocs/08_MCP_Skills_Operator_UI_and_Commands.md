# 08_MCP_Skills_Operator_UI_and_Commands

> 이 문서는 `01_Implementation_Spine.md`의 Step 09를 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
MCP Skills, Operator UI, and Commands

## 목적
operator가 shell 없이도 open obligations, stale tickets, last capsule, resume 상태를 읽고 진단할 수 있게 한다. v0 UI는 **read-only**로 제한한다.

## 이 모듈이 시스템에서 담당하는 책임
- MCP inspect commands 제공
- local read-only inspector UI 제공
- recovery/debug command surface 제공
- operator에게 state visibility 제공
- core state mutation path를 UI로부터 격리

## 선행 의존성
- `07_Resume_Gate_Verify_and_Attempt_Families.md`
- `09_Config_Observability_Ops_and_Recovery.md`

## 후속 의존성
- release packaging
- benchmark demos

## 입력 / 출력
### 입력
- session DB
- last_good_decision_capsule.json
- resume_gate.json
- logs/metrics

### 출력
- MCP command responses
- local UI JSON/API responses
- recovery command output

## 사용자 역할
- **Lead Operator**: 현재 session 상태 확인, stale 원인 진단, blocked reason 확인
- **Developer**: obligation/assertion/evidence 연결 상태 확인
- **Evaluator**: benchmark 결과 확인

## 주요 화면 목록
1. Session Summary
2. Open Obligations
3. Stale / Revalidation Queue
4. Last Decision Capsule
5. Verify Results / Attempt Families
6. Recovery / Diagnostics

## 화면별 목적
### 1. Session Summary
- 현재 session id, repo head, dirty, safe-resume, block reason 표시

### 2. Open Obligations
- open/reopened/blocked obligation 목록, priority, last evidence timestamp 표시

### 3. Stale / Revalidation Queue
- live/stale/revalidated ticket, trigger_ref, required rechecks 표시

### 4. Last Decision Capsule
- 마지막 audit pass capsule과 audit report 표시

### 5. Verify Results / Attempt Families
- 최근 verify ladder 결과와 repeated failure family 표시

### 6. Recovery / Diagnostics
- DB health, artifact 존재 여부, recent fail-open logs 표시

## 화면별 입력/출력
- 입력: session id, optional filters(status/priority/path)
- 출력: read-only JSON / rendered markdown/text
- write action: v0에서는 없음

## 화면 상태
- loading
- loaded
- empty
- stale-warning
- safe-resume
- db-corruption-fallback

## API 의존성
- SessionRepository
- ObligationRepository
- InvalidationRepository
- CapsuleRepository
- VerifyRepository
- AttemptFamilyRepository
- log/metric reader

## 에러 상태
- DB open 실패
- artifact file missing
- corrupted snapshot
- session not found

## UX상 필수 보호장치
- 수동 unblock 버튼 금지
- direct DB mutation 금지
- stale object를 live object처럼 시각적으로 혼동시키지 않기
- block reason / required rechecks를 항상 분리 표시

## 최소 구현 버전과 확장 버전
### 최소 구현 v0
- CLI/MCP inspect commands
- localhost read-only inspector
- no auth (local only)
- no writes

### 확장 v1
- diff view
- audit history
- benchmark report viewer

### 확장 v2
- operator notes
- manual revalidation workflow
- filtered drill-down

## 데이터 계약(contract)

### MCP inspect commands
- `inspect_obligations(session_id)`
- `inspect_stale(session_id)`
- `inspect_capsule(session_id)`
- `inspect_resume_status(session_id)`
- `inspect_verify(session_id)`
- `inspect_attempt_families(session_id)`

### local UI endpoint examples
```text
GET /api/session/:id/summary
GET /api/session/:id/obligations
GET /api/session/:id/stale
GET /api/session/:id/capsule/latest
GET /api/session/:id/verify
GET /api/session/:id/attempt-families
GET /api/session/:id/diagnostics
```

## 내부 서브컴포넌트
- MCP handlers
- read-only service layer
- local HTTP server
- view models
- diagnostics aggregator

## 상태 전이 또는 처리 흐름
1. operator opens UI or MCP command
2. read-only service loads session data
3. merge DB + artifact + log summaries
4. map domain objects to view model
5. render JSON / HTML / markdown

## 구현 단계(step-by-step)
1. inspect service layer 작성
2. MCP command handlers 작성
3. read-only API routes 작성
4. local UI skeleton 작성
5. diagnostics aggregator 작성
6. stale/live visual distinction 추가
7. safe-resume banners 추가

## 실패 모드 / 예외 상황
- UI가 write path를 가져 safety boundary를 침범
- stale와 live를 같은 색/레이블로 보여 operator 오판 유도
- DB corruption 시 crash instead of fallback
- required rechecks가 화면에 누락되어 block 이유가 अस्पष्ट해짐

## 테스트 전략
- inspect service unit tests
- API contract tests
- local UI smoke tests
- safe-resume display tests
- DB missing/corruption fallback tests

## 완료 기준(Definition of Done)
- operator가 shell 없이 session 상태를 읽을 수 있다
- UI/MCP가 state mutation을 하지 않는다
- block reason / required rechecks / stale queue가 명시된다
- corruption/missing artifact fallback이 동작한다

## 이후 모듈로 넘겨야 할 산출물
- inspect services
- MCP handlers
- local UI scaffold
- diagnostics view models

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  mcp/
    inspect.py
  ui/
    server.py
    routes.py
    view_models.py
    static/
tests/
  test_mcp_inspect.py
  test_ui_api_contracts.py
  test_ui_safe_resume.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
class InspectService:
    def session_summary(self, session_id: str) -> dict: ...
    def obligations(self, session_id: str) -> list[dict]: ...
    def stale_queue(self, session_id: str) -> list[dict]: ...
    def latest_capsule(self, session_id: str) -> dict: ...

class DiagnosticsService:
    def runtime_health(self, session_id: str) -> dict: ...
```
