# 체크리스트 답변서

미션 체크리스트의 모든 항목에 대해 **충족 근거(코드·테스트·실행 방법)**와 **설명 답변**을 정리했습니다.
리뷰어가 질문하면 해당 항목을 펼쳐 바로 답할 수 있도록 구성했습니다.

> 표기: 📂 코드 위치 · 🧪 자동 테스트 · ▶️ 직접 확인 명령
> 모든 명령은 `python -m budget_app` 으로 시작합니다. 전체 흐름은 `bash examples/demo.sh` (Windows: `examples\demo.ps1`) 한 번으로 재현됩니다.

- [항목 1. 기능 동작](#항목-1-기능-동작)
- [항목 2. 구조 설계](#항목-2-구조-설계)
- [항목 3. 핵심 문법의 원리](#항목-3-핵심-문법의-원리)
- [항목 4. 확장 질문](#항목-4-확장-질문)

---

## 항목 1. 기능 동작

### 1-1. add / list / search / summary / export / import / update / delete 가 요구사항대로 동작하는가 ✅

- ▶️ `bash examples/demo.sh` → 실제 출력: [`docs/demo-session.md`](demo-session.md)
- 🧪 `tests/test_cli.py::ScenarioTest`, `AddTest`, `tests/test_services.py`

| 명령 | 요구사항 | 구현 |
| --- | --- | --- |
| `add` | 대화형 입력, 생성된 id 출력 | 날짜→타입→카테고리→금액→메모→태그 순서로 묻고 `[저장 완료] id=TX-000012`. 틀리면 이유를 보여주고 다시 물음 |
| `list --limit N` | 최신순, 스트리밍 | 제너레이터 + 크기 N 힙. 기본 20건, `--plain` 은 과제 예시 형식 |
| `search` | `--from/--to/--category/--type/--q/--tag`, 최신순 | 모든 조건 AND. `--month`, `--limit` 추가 지원 |
| `summary --month --top` | 총수입/총지출/잔액 + 지출 TOP N, 데이터 없으면 "데이터 없음" | 예산이 있으면 사용률·초과 경고 |
| `export --out --month` 또는 `--from/--to` | 기간 조건 필수, CSV 저장, 건수 출력 | `[완료] export.csv (12 records)`. 기존 파일은 `--force` 없이 덮어쓰지 않음 |
| `import --from` | 일괄 등록, 처리 건수 출력 | `[완료] imported=5, skipped=0` (부분 성공 / `--atomic` / `--dry-run`) |
| `update --id` | 옵션 방식으로 고정 | 지정한 필드만 변경, 바뀐 내용을 `amount: 15000 -> 18000` 형식으로 출력 |
| `delete --id` | 없는 id 처리 | 없는 id 는 `[오류] … 찾을 수 없습니다` + 종료 코드 3 |

### 1-2. 재실행 후에도 데이터가 유지되는가 (저장 파일 3개 이상) ✅

- 📂 `storage.py::DataPaths` — `transactions.jsonl`, `categories.jsonl`, `budgets.jsonl` (+ 보너스 `recurring.jsonl`)
- 🧪 `test_storage.py::test_data_survives_reopen`, `test_cli.py::test_restart_keeps_data`
- ▶️ `python -m budget_app add` 실행 후 프로그램을 종료하고 `python -m budget_app list` → 그대로 보임. `data/` 폴더의 파일을 메모장으로 열어도 한 줄씩 JSON 으로 저장된 것을 볼 수 있습니다.

처음 실행하면 파일이 없으므로 자동으로 만들고 `[안내] 데이터 파일을 만들었습니다` 를 출력합니다.

### 1-3. category add / list / remove 가 정상 동작하는가 (사용 중인 카테고리 처리 포함) ✅

- 🧪 `test_cli.py::test_category_commands`, `test_services.py::CategoryServiceTest`

```console
$ python -m budget_app category remove food
[오류] 카테고리 'food' 는 거래 3건에서 사용 중이라 삭제할 수 없습니다.
[힌트] --replace-with <다른 카테고리> 를 지정하면 거래를 옮긴 뒤 삭제합니다.
$ python -m budget_app category remove food --replace-with etc
[삭제 완료] category=food (거래 3건을 'etc' 로 옮김)
```

요구사항의 두 방식(삭제 막기 / 대체 카테고리 요구)을 모두 제공합니다. 기본은 **막고**, `--replace-with` 를 주면 거래와 반복 규칙을 옮긴 뒤 삭제합니다. `category list` 는 카테고리별 사용 건수를 함께 보여줘서 지우기 전에 영향 범위를 알 수 있습니다. 카테고리 이름은 소문자로 정규화하므로 `Food` 와 `food` 가 따로 생기지 않습니다.

### 1-4. budget set 이 저장되며 summary 에서 예산 사용률·초과 여부가 출력되는가 ✅

- 🧪 `test_cli.py::test_budget_and_summary`, `test_over_budget_warning`

```console
$ python -m budget_app budget set --month 2024-01 --amount 500000
[저장 완료] 2024-01 예산 500,000원
$ python -m budget_app summary --month 2024-01 --top 3
[2024-01 월별 요약]
총 수입: 3,000,000원
총 지출: 215,000원
잔액: 2,785,000원
예산: 500,000원 (사용률 43.0%) [#########...........]
남은 예산: 285,000원
```

사용률 80% 이상이면 `[주의]`, 100% 초과면 `[경고] 예산을 15,000원 초과했습니다!` 를 출력합니다. 같은 달 예산을 다시 설정하면 덮어씁니다(upsert). `budget show`, `budget list` 로 조회합니다.

### 1-5. import / export 가 명시된 CSV 스키마(UTF-8, 헤더, 컬럼)로 동작하는가 ✅

- 📂 `services.py::ImportExportService` — `CSV_COLUMNS = ("date", "type", "category", "amount", "memo", "tags")`
- 🧪 `test_services.py::test_export_round_trip_preserves_schema` (내보낸 파일을 다른 폴더로 다시 가져와 합계가 같은지 확인)

```csv
date,type,category,amount,memo,tags
2024-01-15,expense,food,15000,점심,meal
2024-01-20,expense,food,30000,저녁 회식,"meal,team"
```

UTF-8 + 헤더 + 고정 컬럼 순서. 태그처럼 쉼표가 들어간 값은 `csv` 모듈이 자동으로 따옴표를 붙입니다. import 는 엑셀 BOM 과 헤더 대소문자를 허용하고, UTF-8 이 아닌 파일(cp949)은 "엑셀에서 'CSV UTF-8' 로 저장하세요" 라고 안내합니다.

### 1-6. 잘못된 입력·파일 오류에서 스택트레이스 없이 오류 메시지와 해결 힌트를 출력하는가 ✅

- 📂 `decorators.py::handle_errors`, `errors.py`
- 🧪 `test_cli.py::ErrorHandlingTest`, `HelpTest::test_unknown_command_and_option_exit_with_usage_error`

```console
$ python -m budget_app add
날짜(YYYY-MM-DD, 엔터=오늘): 2024-13-40
[오류] 존재하지 않는 날짜입니다: 2024-13-40
[힌트] 월은 01~12, 일은 그 달의 마지막 날까지 입력하세요.
날짜(YYYY-MM-DD, 엔터=오늘):                ← 같은 질문을 다시 함

$ python -m budget_app list            (transactions.jsonl 2번째 줄을 일부러 망가뜨린 상태)
[오류] transactions.jsonl 의 2번째 줄이 손상되었습니다.
[힌트] 해당 줄을 직접 고치거나 'restore' 로 백업을 복원하세요.
```

예상하지 못한 버그도 `[오류] 예기치 못한 문제가 발생했습니다: …` + `--debug` 안내로 바꾸고, `--debug` 를 붙였을 때만 traceback 을 보여줍니다(`test_unexpected_error_is_hidden_unless_debug`). argparse 의 영문 오류도 같은 형식으로 바꿨습니다.

### 1-7. 오류 상황에서 종료 코드가 0 이 아님을 확인할 수 있는가 ✅

- 🧪 `test_cli.py::test_all_error_exit_codes_are_non_zero`

```console
$ python -m budget_app delete --id TX-999999; echo $?        # PowerShell: $LASTEXITCODE
[오류] id=TX-999999 거래를 찾을 수 없습니다.
3
```

| 코드 | 의미 |
| --- | --- |
| 0 | 성공 |
| 1 | 예기치 못한 오류 |
| 2 | 잘못된 입력·옵션 |
| 3 | 대상 없음 |
| 4 | 상태 충돌 (사용 중 카테고리, 기존 파일) |
| 5 | 데이터 손상·입출력 실패 |
| 130 | 사용자 취소 (Ctrl+C, EOF) |

에러 종류마다 다른 코드를 쓰는 이유는 쉘 스크립트나 cron 이 "없는 데이터라 괜찮다(3)" 와 "파일이 손상됐다(5)" 를 구분해 다르게 대응할 수 있게 하기 위해서입니다.

---

## 항목 2. 구조 설계

### 2-1. 3개 이상 모듈로 분리했고, 각 모듈의 책임을 "어떻게" 나눴는지 설명할 수 있는가 ✅

9개 모듈을 **계층**으로 나눴습니다. 나눈 기준은 "**이 코드를 바꾸게 만드는 이유가 무엇인가**" 입니다.

| 바꾸는 이유 | 고치는 모듈 |
| --- | --- |
| 화면 문구, 옵션 이름이 바뀜 | `cli.py`, `formatting.py` |
| 기능 규칙이 바뀜 (예: 카테고리 삭제 정책) | `services.py` |
| 저장 형식이 바뀜 (JSONL → CSV/SQLite) | `storage.py` |
| 데이터 항목이 바뀜 (필드 추가) | `models.py` |
| 입력 허용 규칙이 바뀜 | `validators.py` |
| 로그·에러 처리 방식이 바뀜 | `decorators.py`, `errors.py` |

의존은 `cli → services → storage → models` 한 방향입니다. 그래서 서비스는 화면 없이 값을 반환하고, `tests/test_services.py` 처럼 CLI 를 거치지 않고 바로 테스트할 수 있습니다. 이 방향은 `test_structure.py::test_layer_dependency_direction` 이 import 문을 분석해서 검사합니다(아래 계층이 위 계층을 import 하면 실패).

📂 상세: [`design.md` 1절](design.md#1-계층-구조)

### 2-2. 최소 2개 이상의 클래스에 부여한 책임 경계를 "어떻게" 정했는지 설명할 수 있는가 ✅

데이터 모델 5개(dataclass), 저장소 6개, 서비스 7개, 결과 값 객체 3개 클래스가 있습니다. 경계를 정한 예를 세 쌍으로 설명하면:

1. **`JsonlFile` ↔ `TransactionRepository`**: `JsonlFile` 은 "파일 한 개를 한 줄씩 읽고, 붙이고, 안전하게 바꿔 쓰기"만 압니다. 거래가 뭔지 모릅니다. `TransactionRepository` 는 레코드를 `Transaction` 으로 바꾸고 id 로 찾는 일을 합니다. 그래서 카테고리·예산·반복 규칙 저장소가 모두 `JsonlFile` 을 재사용하고, 원자적 교체 로직은 한 곳에만 있습니다.
2. **`CategoryStore` ↔ `CategoryService`**: 저장소의 `remove()` 는 "사용 중인지" 를 검사하지 않습니다. 사용 여부는 거래 파일을 봐야 알고, "막을지/옮길지" 는 정책이기 때문입니다. 정책은 서비스가, 파일 조작은 저장소가 맡습니다.
3. **`SummaryService` ↔ `MonthlySummary`**: 서비스는 계산만 하고 결과를 값 객체로 돌려줍니다. 사용률(`budget_usage`), 초과액(`over_budget`), TOP N(`top_expenses`)은 값 객체의 프로퍼티입니다. CLI 는 이 값을 읽어서 출력만 합니다 → 출력 형식을 바꿔도 계산 코드는 그대로입니다.

또 `TransactionRepository` 에는 "전체를 리스트로 반환하는 메서드"를 일부러 만들지 않았습니다. 없는 기능은 실수로 쓸 수도 없어서, 스트리밍 원칙을 구조로 강제합니다.

### 2-3. 파일 기반 update / delete 를 "어떻게" 안전하게 처리했는지 설명할 수 있는가 ✅

- 📂 `storage.py::JsonlFile.rewrite`, `TransactionRepository.update/delete`
- 🧪 `test_failed_rewrite_keeps_original_and_cleans_temp_file`, `test_update_and_delete_unknown_id_do_not_touch_file`

JSONL 은 줄 길이가 달라 중간을 고칠 수 없으므로 파일을 새로 씁니다. 그 과정을 **임시 파일 + 원자적 교체**로 처리합니다.

1. 같은 폴더에 임시 파일을 만든다 (`os.replace` 는 같은 파일 시스템 안에서만 원자적).
2. 원본을 한 줄씩 읽으며(제너레이터) 바뀐 내용을 임시 파일에 쓰고 `flush` + `fsync` 로 디스크까지 기록한다.
3. `os.replace(임시, 원본)` 으로 한 번에 교체한다. 운영체제가 "옛 파일 아니면 새 파일" 둘 중 하나만 보이도록 보장한다.
4. 2단계에서 예외가 나면 임시 파일만 지우고 원본은 건드리지 않는다.

없는 id 를 수정/삭제하려 하면 끝까지 읽은 뒤 제너레이터가 `NotFoundError` 를 던지고, 4단계 규칙에 따라 임시 파일만 지워집니다. 원본은 수정 시각도 바뀌지 않습니다. 처음에는 존재 확인을 위해 파일을 따로 두 번 더 읽었는데, 이 구조로 바꿔서 순회를 3회 → 1회로 줄였습니다([`performance.md`](performance.md#측정-중-발견해-개선한-점)).

---

## 항목 3. 핵심 문법의 원리

### 3-1. list / search 를 제너레이터로 스트리밍한 방식을 "어떻게" 구현했고 "왜" 유리한지 설명할 수 있는가 ✅

**어떻게**

```python
# storage.py — 파일을 한 줄씩 읽어 하나씩 넘긴다
def iter_records(self) -> Iterator[Record]:
    with self.path.open("r", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)

# services.py — 스트림 위에 조건과 상위 N 선택을 겹친다
def list_latest(self, limit: int) -> List[Transaction]:
    return heapq.nlargest(limit, self.repo.iter_all(), key=latest_first_key)

def search(self, flt: SearchFilter, limit=None) -> List[Transaction]:
    matches = (tx for tx in self.repo.iter_all() if flt.matches(tx))   # 제너레이터 식
    ...
```

`yield` 는 값을 하나 넘기고 함수를 그 자리에서 **멈춥니다**. 다음 값을 달라고 할 때 멈춘 곳부터 한 줄을 더 읽습니다. 그래서 파일 → 레코드 → `Transaction` → 조건 필터 → 힙으로 한 건씩 흘러가고, 메모리에는 처리 중인 한 건과 결과(상위 N개)만 남습니다.

**왜 유리한가**

- 10만 건(20 MB)에서 `list --limit 20` 최대 메모리 **59 KB**, 전체를 리스트로 읽으면 **약 60 MB** ([`performance.md`](performance.md)). 데이터가 100배 늘어도 메모리는 거의 그대로입니다.
- 첫 결과가 나오기 전에 파일 전체를 기다릴 필요가 없고, 중간에 멈추면(예: 찾았으면 끝) 나머지는 읽지도 않습니다(`get()` 이 그렇게 동작).
- 🧪 `test_storage.py::StreamingMemoryTest` 가 "스트리밍 방식의 최대 메모리 × 10 < 전체 로드 메모리" 를 매번 검증하고, `test_iter_records_is_a_generator` 가 제너레이터 함수인지 확인합니다.

"최신순" 은 날짜 기준이라 파일 순서(등록 순서)와 다릅니다. 전체를 정렬하지 않고 크기 N 의 힙(`heapq.nlargest`)으로 상위 N개만 유지해서 O(전체 × log N) 시간, O(N) 메모리로 처리합니다.

### 3-2. 데코레이터로 분리한 공통 기능이 무엇이며 "왜" 분리가 필요했는지 설명할 수 있는가 ✅

- 📂 `decorators.py` — `@handle_errors`, `@log_command`, `@timed`, 그리고 셋을 묶은 `@command`

| 데코레이터 | 공통 기능 |
| --- | --- |
| `@handle_errors` | 예외 → `[오류]`/`[힌트]` + 종료 코드. 스택트레이스 숨김 |
| `@log_command` | 명령·인자·종료 코드·소요 시간을 `data/app.log` 에 JSON 한 줄로 기록 (실패한 명령도) |
| `@timed` | 실행 시간 측정, `--verbose` 시 `[시간] list 0.6ms` 출력 |

**왜 분리했나**: 13개 명령 핸들러 모두에 같은 `try/except`, 로그 기록, 시간 측정이 필요합니다. 핸들러 안에 쓰면 ① 같은 코드가 13번 반복되고 ② 하나를 고칠 때 13곳을 고쳐야 하며 ③ 기능 코드가 부가 코드에 묻혀 읽기 어려워집니다. 데코레이터로 빼면 핸들러는 기능만 남고(`cmd_delete` 는 4줄), 정책을 바꾸면 `decorators.py` 한 곳만 고치면 됩니다.

**동작 원리**: `@command` 는 `cmd_delete = handle_errors(log_command(timed(cmd_delete)))` 와 같습니다. 데코레이터는 함수를 받아 "앞뒤에 일을 덧붙인 새 함수" 를 돌려줍니다. 에러 처리를 가장 바깥에 둬서 로그 단계에서 생긴 문제도 사용자 메시지로 바뀌게 했습니다. `functools.wraps` 로 원래 이름·docstring 을 보존합니다. 🧪 `test_decorators.py`, `test_every_command_handler_is_decorated`

### 3-3. 타입 힌트를 적용해 얻는 이점을 실제 코드 예로 "어떻게" 확인했고 "왜" 도움이 되는지 설명할 수 있는가 ✅

**실제 코드 예**

```python
def iter_all(self) -> Iterator[Transaction]: ...      # 한 번만 순회 가능한 스트림
def list_latest(self, limit: int) -> List[Transaction]: ...   # 다 모은 결과
```
반환 타입만 보고도 앞의 것은 `len()` 을 쓸 수 없고 두 번 순회할 수 없다는 걸 압니다.

```python
amount: int          # Transaction 필드
type: TxType         # Enum
```
`float` 가 아닌 `int` 로 "금액에 소수점 오차가 없다" 는 것을, 문자열이 아닌 `TxType` 으로 "`incom` 같은 오타가 들어올 자리가 없다" 는 것을 타입으로 표현했습니다.

```python
def update(self, tx_id: str, change: Callable[[Transaction], Transaction]) -> Tuple[Transaction, Transaction]: ...
```
"거래를 받아 거래를 돌려주는 함수를 넘기면 (수정 전, 수정 후)를 돌려준다" 는 계약이 시그니처에 다 있습니다.

**어떻게 확인했나**: 성능 개선 때 `update` 의 반환을 `Transaction` → `Tuple[Transaction, Transaction]` 으로 바꿨습니다. 시그니처를 먼저 고치고 호출부를 따라가며 맞췄고, VS Code(Pylance)나 `mypy` 로 검사하면 예전 방식으로 쓰는 곳이 바로 표시됩니다. 🧪 `test_public_api_has_type_hints` 는 공개 함수에 반환 타입이 빠지지 않았는지 검사합니다.

**왜 도움이 되나**: 호출하는 쪽이 구현을 읽지 않아도 무엇을 넣고 무엇을 받는지 알 수 있고(문서 역할), 잘못된 사용을 실행 전에 도구가 잡아줍니다. 타입 힌트는 실행 시 강제되지 않으므로, 실제 값 검증은 `validators.py` 가 따로 합니다.

---

## 항목 4. 확장 질문

### 4-1. JSONL 과 CSV 중 선택한 저장 포맷의 장단점을 비교하고 "왜" 그 포맷을 택했는지 근거를 말할 수 있는가 ✅

**JSONL 을 택했습니다.**

| 기준 | JSONL | CSV |
| --- | --- | --- |
| 스트리밍 | 줄 = 객체 1개라 `for line in f` 로 끝 | 가능하지만 따옴표 안의 줄바꿈 때문에 "한 줄 = 한 행" 이 깨질 수 있음 |
| 목록 값(`tags`) | `["meal","team"]` 그대로 | `"meal,team"` 처럼 구분자 규칙이 따로 필요 |
| 필드 추가 | 옛 데이터에 필드가 없어도 `.get()` 으로 읽힘 → 보너스에서 `source`, `updated_at` 를 추가할 때 마이그레이션 불필요 | 헤더와 모든 행의 컬럼 수를 맞춰야 함 |
| 타입 | 숫자/문자열/null 구분 | 전부 문자열이라 읽을 때마다 변환 |
| 사람이 보기 | 텍스트 편집기는 가능, 엑셀은 불편 | 엑셀로 바로 열림 |
| 용량 | 키 이름이 매 줄 반복되어 더 큼 | 작음 |

근거: 이 프로그램은 **구조가 진화하는 데이터**(태그 목록, 반복 내역 출처, 수정 시각)를 다루고 저장 파일은 프로그램이 읽습니다. 사람이 엑셀로 보는 용도는 `export`(CSV)가 맡으므로, 내부 저장은 구조 표현과 스트리밍에 강한 JSONL, 외부 교환은 CSV 로 역할을 나눴습니다.

### 4-2. 거래가 10만 건으로 늘어난다면 병목이 어디이며 "어떻게" 개선할지 설명할 수 있는가 ✅

실제로 10만 건(20.5 MB)을 만들어 측정했습니다(`python scripts/benchmark.py`, [`performance.md`](performance.md)).

| 작업 | 10만 건 | 최대 메모리 |
| --- | ---: | ---: |
| list / search / summary | 약 0.8 ~ 1.0초 | 59 KB / 1.9 MB / 49 KB |
| add | 0.5초 | 48 KB |
| update / delete | 약 1.7초 | 65 KB |

**메모리는 문제가 없고(스트리밍 덕분), 시간이 O(n) 으로 늘어나는 것이 병목**입니다. 원인과 개선 방향:

1. **모든 조회가 전체 파일 파싱** → 월별 파일 분할(`transactions/2024-01.jsonl`)로 summary 는 한 달 파일만 읽게 하거나, 월별 합계를 미리 집계해 둡니다.
2. **update/delete 가 파일 전체를 다시 씀** → 수정·삭제를 "새 버전 / 삭제 표시" 줄로 append 하고, 주기적으로 압축(compaction)하는 로그 구조로 바꿉니다.
3. **add 가 다음 id 를 찾으려고 전체를 훑음** → `meta.json` 에 `next_id` 를 저장하면 O(1).
4. **근본 해결**: 표준 라이브러리 `sqlite3` 로 저장소 계층만 교체합니다. 인덱스(`date`, `category`)와 트랜잭션을 그대로 얻고, 계층을 나눠 둔 덕분에 `storage.py` 만 바꾸면 서비스·CLI 는 그대로입니다.

측정 과정에서 update/delete 의 불필요한 사전 순회 2회를 없애 이미 한 번 개선했습니다.

### 4-3. import CSV 에 일부 깨진 행이 섞이면 "어떻게" 처리해 사용자 신뢰를 지킬지 설명할 수 있는가 (부분 성공 / 롤백 / 리포트) ✅

- ▶️ `python -m budget_app import --from examples/broken_import.csv` (6행 중 4행이 깨진 예시 파일)
- 🧪 `test_services.py::ImportExportTest`

세 가지 전략을 모두 제공하고, 사용자가 상황에 맞게 고르게 했습니다.

```console
$ python -m budget_app import --from examples/broken_import.csv            # 기본: 부분 성공
[건너뜀] 3번째 줄: 존재하지 않는 날짜입니다: 2024-02-30
[건너뜀] 4번째 줄: 등록되지 않은 카테고리: unknown
[건너뜀] 5번째 줄: 금액은 0보다 커야 합니다: -100
[건너뜀] 6번째 줄: 허용되지 않는 타입입니다: refund
[완료] imported=2, skipped=4
[힌트] 거부된 행은 'examples/broken_import.rejected.csv' 에 사유와 함께 저장했습니다. 고쳐서 다시 import 하세요.

$ python -m budget_app import --from examples/broken_import.csv --atomic   # 롤백
[롤백] 오류가 있어 아무것도 가져오지 않았습니다: imported=0, skipped=4

$ python -m budget_app import --from examples/broken_import.csv --dry-run  # 미리 검증
[검증] 가져올 수 있는 행 2건, 오류 4건 — 저장하지 않았습니다 (--dry-run)
```

| 전략 | 장점 | 단점 | 언제 |
| --- | --- | --- | --- |
| 부분 성공 (기본) | 멀쩡한 데이터는 바로 쓸 수 있음 | 일부만 들어간 상태가 생김 | 서로 독립적인 거래 (대부분의 가계부 데이터) |
| 롤백 (`--atomic`) | "전부 아니면 전무" 라 합계가 어긋나지 않음 | 한 행 때문에 전체가 막힘 | 은행 내역처럼 일부만 들어가면 잔액이 틀어지는 데이터 |
| 리포트 | 무엇이 왜 빠졌는지 숨기지 않음 | | 모든 모드에 공통 |

사용자 신뢰를 지키는 원칙은 세 가지입니다.

1. **조용히 버리지 않는다** — 건너뛴 행마다 줄 번호와 이유를 보여줍니다.
2. **고칠 수단을 준다** — 거부된 행만 `.rejected.csv` 에 `error` 컬럼을 붙여 저장해서, 고친 뒤 그 파일만 다시 import 하면 됩니다.
3. **반쯤 저장된 상태를 만들지 않는다** — `--atomic` 은 기존+신규를 임시 파일에 다 쓴 뒤 한 번에 교체하므로, 저장 도중 실패해도 원본이 그대로입니다. 같은 파일을 두 번 넣는 실수는 `--skip-duplicates` 로 막습니다.
