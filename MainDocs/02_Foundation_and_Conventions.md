# 02_Foundation_and_Conventions

> 이 문서는 `01_Implementation_Spine.md`의 Step 00을 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Foundation and Conventions

## 목적
후속 구현이 흔들리지 않도록 패키지 구조, enum, 네이밍, 디렉터리, JSON 출력 규율, Phase 1/2 경계를 고정한다.

## 이 모듈이 시스템에서 담당하는 책임
- 변경 불가 결정 고정
- 공통 enum/status naming 고정
- `.egtsr/` artifact layout 정의
- hook stdout JSON discipline 정의
- Phase 1 correctness path와 Phase 2 optimization path 분리
- 테스트 fixture 디렉터리 구조 정의

## 선행 의존성
- 없음

## 후속 의존성
- 모든 후속 모듈

## 입력 / 출력
### 입력
- 기존 구현 문서의 고정 결정
- Claude hook runtime 제약
- local runtime packaging 제약

### 출력
- 공통 constants/enums
- package layout
- directory convention
- config skeleton
- test fixture naming rules

## 데이터 계약(contract)

### 표준 상태 enum
```python
class ObligationStatus(StrEnum):
    OPEN = "open"
    LOCALIZED = "localized"
    ADDRESSED = "addressed"
    VERIFIED = "verified"
    REOPENED = "reopened"
    BLOCKED = "blocked"

class AssertionStatus(StrEnum):
    SPECULATIVE = "speculative"
    SUPPORTED = "supported"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    STALE = "stale"

class InvalidationStatus(StrEnum):
    LIVE = "live"
    STALE = "stale"
    REVALIDATED = "revalidated"
    CLOSED = "closed"

class VerifyPhase(StrEnum):
    TARGETED = "targeted"
    IMPACTED_SURFACE = "impacted_surface"
    BROAD_SMOKE = "broad_smoke"
```

### hook stdout contract
- stdout은 JSON object 하나만 출력
- 일반 텍스트 금지
- block도 exit code가 아니라 JSON으로 표현
- 파싱 실패 시 기본은 fail-open

### artifact 경로
```text
.egtsr/
  session.db
  runtime.log
  last_good_decision_capsule.json
  resume_gate.json
  raw_events/
  debug/
  reports/
```

## 내부 서브컴포넌트
- `egtsr_runtime/constants.py`
- `egtsr_runtime/enums.py`
- `egtsr_runtime/paths.py`
- `egtsr_runtime/config.py`
- `tests/fixtures/hooks/`
- `tests/fixtures/state/`
- `tests/fixtures/compiler/`

## 상태 전이 또는 처리 흐름
1. config load
2. path bootstrap
3. enum/contract import
4. hook adapters and services consume same constants

## 구현 단계(step-by-step)
1. package root 생성
2. `.egtsr` 표준 경로 유틸 작성
3. enum/constants 작성
4. JSON serializer helper 작성
5. config dataclass 작성
6. fixture directory convention 생성
7. README 수준 개발 규약 추가

## 실패 모드 / 예외 상황
- enum 문자열이 문서와 코드에서 어긋남
- artifact 경로가 OS별로 달라져 tests가 불안정
- stdout에 debug text가 섞여 hook parse 실패
- Phase 1 code가 compact hooks를 authority처럼 사용

## 테스트 전략
- enum serialization tests
- path resolution tests
- stdout JSON purity tests
- config default load tests

## 완료 기준(Definition of Done)
- 공통 enum/status가 코드와 문서에서 일치한다
- `.egtsr` artifact 경로가 표준화된다
- hook stdout helper가 JSON-only discipline을 강제한다
- fixture 디렉터리 구조가 고정된다

## 이후 모듈로 넘겨야 할 산출물
- enums/constants module
- config schema skeleton
- path helpers
- fixture layout

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  __init__.py
  constants.py
  enums.py
  paths.py
  config.py
  jsonio.py
tests/
  fixtures/
    hooks/
    state/
    compiler/
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
@dataclass(slots=True)
class RuntimeConfig:
    repo_root: str
    egtsr_dir: str
    db_path: str
    enable_compact_hooks: bool = False
    max_decision_tokens: int = 900

def ensure_runtime_dirs(repo_root: str) -> "RuntimePaths": ...
def json_stdout(payload: dict) -> str: ...
```
