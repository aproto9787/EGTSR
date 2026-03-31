# 03_Domain_State_and_SQLite_Model

> 이 문서는 `01_Implementation_Spine.md`의 Step 01을 지원한다.  
> 구현 순서의 authority는 `01`에 있다.

## 모듈명
Domain State and SQLite Model

## 목적
EGTSR의 authoritative task state를 단일 SQLite 파일과 typed repository로 고정한다.

## 이 모듈이 시스템에서 담당하는 책임
- sessions / repo_state / obligations / evidence / assertions / invalidation_tickets / attempt_families / verify_results / capsules / events 저장
- 상태 enum, foreign-key 관계, update semantics 정의
- transaction boundary 정의
- fixture seed / snapshot load 지원

## 선행 의존성
- `02_Foundation_and_Conventions.md`

## 후속 의존성
- hook bootstrap
- decision compiler
- evidence ingest
- invalidation
- resume gate
- verify recorder
- operator UI

## 입력 / 출력
### 입력
- migration commands
- normalized hook event / service calls

### 출력
- stored session state
- queryable typed models
- transaction-safe snapshot

## 데이터 계약(contract)

### 핵심 테이블
```sql
create table sessions (
  id text primary key,
  repo_root text not null,
  branch text,
  head_hash text,
  status text not null,
  created_at text not null,
  updated_at text not null
);

create table repo_state (
  session_id text not null,
  head_hash text,
  dirty integer not null default 0,
  changed_files_json text not null,
  last_scan_at text not null,
  primary key (session_id)
);

create table obligations (
  id text primary key,
  session_id text not null,
  source text not null,
  statement text not null,
  priority integer not null default 50,
  status text not null,
  acceptance_check text,
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null
);

create table evidence (
  id text primary key,
  session_id text not null,
  kind text not null,
  source_tool text not null,
  path text,
  scope_kind text,
  scope_ref text,
  file_hash text,
  polarity text not null default 'positive',
  excerpt text,
  metadata_json text not null default '{}',
  created_at text not null
);

create table assertions (
  id text primary key,
  session_id text not null,
  obligation_id text,
  statement text not null,
  scope_kind text,
  scope_ref text,
  status text not null,
  confidence real not null default 0.5,
  evidence_ids_json text not null,
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null
);

create table invalidation_tickets (
  id text primary key,
  session_id text not null,
  subject_type text not null,
  subject_id text not null,
  trigger_kind text not null,
  trigger_ref text,
  status text not null,
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null
);

create table attempt_families (
  id text primary key,
  session_id text not null,
  obligation_id text,
  signature text not null,
  touched_scope_json text not null,
  fail_count integer not null default 1,
  last_outcome text not null,
  summary text,
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null
);

create table verify_results (
  id text primary key,
  session_id text not null,
  phase text not null,
  outcome text not null,
  affected_obligation_ids_json text not null,
  excerpt text,
  metadata_json text not null default '{}',
  created_at text not null
);

create table capsules (
  id text primary key,
  session_id text not null,
  phase text not null,
  frontier_hash text not null,
  content text not null,
  token_count integer not null,
  audit_pass integer not null,
  audit_report_json text not null,
  created_at text not null
);

create table events (
  id text primary key,
  session_id text not null,
  event_type text not null,
  payload_json text not null,
  created_at text not null
);
```

### repository contract
- domain object는 DB row dict가 아니라 typed model로 반환
- write는 service layer에서 transaction 묶음으로 수행
- session snapshot은 최소한 `sessions + repo_state + capsules + events`까지 atomic 보장

## 내부 서브컴포넌트
- migration runner
- sqlite connection manager
- repositories
  - SessionRepository
  - ObligationRepository
  - EvidenceRepository
  - AssertionRepository
  - InvalidationRepository
  - VerifyRepository
  - AttemptFamilyRepository
  - CapsuleRepository
  - EventRepository
- UnitOfWork

## 상태 전이 또는 처리 흐름
1. DB open
2. migration apply
3. service begins transaction
4. repository CRUD
5. commit or rollback
6. return typed models

## 구현 단계(step-by-step)
1. sqlite connection utility 작성
2. migration SQL 작성
3. dataclass/pydantic domain models 작성
4. repository interface 정의
5. concrete sqlite repository 작성
6. seed helper 작성
7. transaction wrapper 작성
8. round-trip integration tests 작성

## 실패 모드 / 예외 상황
- enum/status가 잘못 저장되어 state transition이 깨짐
- JSON column 직렬화 실패
- transaction 경계가 느슨해 partial write 발생
- changed_files_json 등 list field가 문자열/JSON 혼용으로 깨짐
- file path normalization 누락으로 invalidation matching 실패

## 테스트 전략
- migration success/fresh DB test
- seed/load round-trip test
- transaction rollback test
- enum serialization test
- snapshot atomicity test
- temp-db integration test

## 완료 기준(Definition of Done)
- fresh DB migration 성공
- seed 데이터 round-trip 성공
- 각 repository CRUD 동작
- transaction rollback 시 partial write 없음
- session snapshot save/load 가능

## 이후 모듈로 넘겨야 할 산출물
- DB schema
- typed repositories
- UnitOfWork
- fixture seed helper

## 가능하면 폴더 구조 / 파일 구조
```text
egtsr_runtime/
  db/
    connection.py
    migrations.py
    schema.sql
    uow.py
  models/
    session.py
    obligation.py
    evidence.py
    assertion.py
    invalidation.py
    verify.py
    capsule.py
  repositories/
    sessions.py
    obligations.py
    evidence.py
    assertions.py
    invalidations.py
    verify_results.py
    attempt_families.py
    capsules.py
    events.py
tests/
  test_db_migrations.py
  test_repositories_roundtrip.py
  test_uow_atomicity.py
```

## 가능하면 주요 클래스 / 함수 / 인터페이스 초안
```python
class SessionRepository(Protocol):
    def create(self, session: Session) -> None: ...
    def get(self, session_id: str) -> Session | None: ...
    def update(self, session: Session) -> None: ...

class ObligationRepository(Protocol):
    def list_open(self, session_id: str) -> list[Obligation]: ...
    def upsert(self, obligation: Obligation) -> None: ...
    def mark_status(self, obligation_id: str, status: str) -> None: ...

class UnitOfWork(Protocol):
    sessions: SessionRepository
    obligations: ObligationRepository
    evidence: EvidenceRepository
    assertions: AssertionRepository
    invalidations: InvalidationRepository
    verify_results: VerifyRepository
    attempt_families: AttemptFamilyRepository
    capsules: CapsuleRepository
    events: EventRepository
    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```
