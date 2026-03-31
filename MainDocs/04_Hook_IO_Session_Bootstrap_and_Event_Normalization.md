# 04_Hook_IO_Session_Bootstrap_and_Event_Normalization

> 이 문서는 `01_Implementation_Spine.md`의 Step 02, Step 04를 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Hook I/O, Session Bootstrap, and Event Normalization

## 목적
Claude hook raw stdin JSON을 runtime 내부가 쓰는 normalized envelope로 바꾸고, SessionStart / UserPromptSubmit / PostToolUse / SessionEnd의 최소 동작을 고정한다.

## 이 모듈이 시스템에서 담당하는 책임
- raw hook payload 파싱
- optional/unknown field tolerant normalization
- JSON-only stdout response 생성
- SessionStart bootstrap
- UserPromptSubmit allow/block response skeleton
- PostToolUse/SessionEnd 공통 envelope 처리

## 선행 의존성
- `02_Foundation_and_Conventions.md`
- `03_Domain_State_and_SQLite_Model.md`

## 후속 의존성
- decision compiler
- prompt gate
- evidence ingest
- resume gate
- snapshot writer

## 입력 / 출력
### 입력
- Claude hook raw stdin JSON

### 출력
- internal normalized event envelope
- hook stdout JSON
- raw payload archive entry
- session bootstrap context

## 데이터 계약(contract)

### normalized envelope
```python
@dataclass(slots=True)
class HookEnvelope:
    version: str
    received_at: str
    hook_event_name: Literal["SessionStart","UserPromptSubmit","PostToolUse","SessionEnd"]
    session_id: str
    cwd: str
    transcript_path: str | None
    permission_mode: str | None
    source: str | None
    tool_name: str | None
    tool_use_id: str | None
    prompt: str | None
    raw: dict
```

### top-level hook stdout fields
```json
{
  "suppressOutput": true,
  "systemMessage": "optional",
  "decision": "block",
  "reason": "optional",
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "..."
  }
}
```

### SessionStart raw example
```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../transcript.jsonl",
  "cwd": "/repo",
  "hook_event_name": "SessionStart",
  "source": "startup",
  "model": "claude-sonnet-4-6"
}
```

### UserPromptSubmit raw example
```json
{
  "session_id": "abc123",
  "cwd": "/repo",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Fix the failing auth refresh test"
}
```

### PostToolUse raw example
```json
{
  "session_id": "abc123",
  "cwd": "/repo",
  "hook_event_name": "PostToolUse",
  "tool_name": "Read",
  "tool_input": {"file_path": "/repo/auth/session.py"},
  "tool_response": {"content": "..."},
  "tool_use_id": "toolu_123"
}
```

## 내부 서브컴포넌트
- raw stdin reader
- tolerant JSON parser
- hook event normalizers
- hook response builder
- repo inspector (`git rev-parse HEAD`, dirty check)
- raw event archiver

## 상태 전이 또는 처리 흐름
### SessionStart
1. parse raw JSON
2. normalize envelope
3. archive raw payload
4. load/create session
5. inspect repo head/dirty
6. emit additionalContext summary or safe-resume warning

### UserPromptSubmit
1. parse raw JSON
2. normalize envelope
3. load session state
4. call compiler/audit/prompt gate
5. emit allow or block JSON

### PostToolUse
1. parse raw JSON
2. normalize envelope
3. archive raw payload
4. pass to ingest pipeline
5. emit warn-only or silent success JSON

### SessionEnd
1. parse raw JSON
2. normalize envelope
3. snapshot session
4. emit silent success JSON

## 구현 단계(step-by-step)
1. envelope dataclass 작성
2. raw parser 구현
3. event-specific validators 구현
4. response builder 구현
5. repo inspector 구현
6. raw archive writer 구현
7. SessionStart bootstrap service 구현
8. four-hook fixtures 추가

## 실패 모드 / 예외 상황
- optional field 부재로 parser crash
- unknown field drop으로 디버깅 정보 손실
- stdout에 debug text가 섞여 hook parse 실패
- repo inspect 실패로 SessionStart 자체가 죽음
- compact source를 startup과 잘못 동일시

## 테스트 전략
- raw JSON fixture parse tests
- optional field absent tests
- unknown field preserve tests
- stdout JSON purity tests
- source=`resume|compact` bootstrap tests
- repo dirty/head changed fixture tests

## 완료 기준(Definition of Done)
- 네 개 hook fixture를 모두 정상 파싱
- unknown field가 raw archive에 남는다
- SessionStart가 session create/load + repo inspect 수행
- UserPromptSubmit allow/block skeleton이 출력 가능
- SessionEnd가 snapshot trigger를 호출 가능

## 이후 모듈로 넘겨야 할 산출물
- HookEnvelope
- hook response builder
- SessionStart bootstrap service
- raw archive writer
- parser fixtures

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  hooks/
    envelopes.py
    parser.py
    responses.py
    session_start.py
    user_prompt_submit.py
    post_tool_use.py
    session_end.py
  services/
    repo_inspector.py
    raw_archive.py
tests/
  fixtures/hooks/
    session_start_startup.json
    session_start_resume.json
    session_start_compact.json
    user_prompt_submit_edit.json
    post_tool_use_read.json
    session_end.json
  test_hook_parser.py
  test_session_start_bootstrap.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
def parse_hook_stdin(raw_text: str) -> HookEnvelope: ...
def build_allow_response(hook_name: str, additional_context: str, system_message: str | None = None) -> dict: ...
def build_block_response(reason: str, additional_context: str, system_message: str | None = None) -> dict: ...

class SessionBootstrapService:
    def load_or_create(self, envelope: HookEnvelope) -> "SessionBootstrapResult": ...

@dataclass(slots=True)
class SessionBootstrapResult:
    session_id: str
    repo_head: str | None
    dirty: bool
    safe_resume: bool
    additional_context: str | None
```
