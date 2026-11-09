# 동료 평가 피드백 반영 체크리스트

동료 평가에서 16개 항목 모두 PASS 를 받았고, 항목마다 "부족한 점 · 보완"을 받았습니다.
이 문서는 그 보완 요청을 하나씩 어디에 어떻게 반영했는지 기록합니다.
문서에 넣은 출력은 모두 빈 임시 폴더에서 실제로 실행한 결과입니다.

| # | 평가 항목 (근거) | 받은 보완 요청 | 반영 내용 | 반영 위치 | 상태 |
| --- | --- | --- | --- | --- | --- |
| 1 | 핵심 명령 구현 (`cli.py` 핸들러 등록) | 주요 명령의 짧은 실행 예시(출력 포함)를 README 에 | import · budget set · list · list --plain · search · summary · update · delete 를 차례로 실행한 실제 출력 | README [실행 예시](../README.md#실행-예시) | ✅ |
| 2 | 저장 파일 (`data/transactions.jsonl`) | 재실행 전/후 파일 내용 스냅샷 | 빈 파일 → add(프로세스 종료) → 새 프로세스로 list → `cat` 으로 JSON 한 줄 확인, 5단계 기록 | README [재실행 후에도 데이터가 남는지 확인](../README.md#재실행-후에도-데이터가-남는지-확인) | ✅ |
| 3 | 카테고리 삭제 정책 (`--replace-with`) | 카테고리 삭제 오류 시나리오 예시 | 사용 중(4) · 대체 카테고리 없음(3) · 없는 카테고리(3) · 성공 사례의 실제 메시지와 `echo $?`, 상황별 해결 표 | README [카테고리 삭제 오류 시나리오](../README.md#카테고리-삭제-오류-시나리오) | ✅ |
| 4 | 예산 사용률 · 초과 경고 (`cli.py` summary) | 예산 없음 · 주의(80%) · 초과 경계값 테스트 | 경계값 테스트 6개(`BudgetThresholdTest`). 쓰는 중 79.99% 가 화면엔 80.0% 인데 주의가 안 뜨는 어긋남을 찾아 수정(`cli.py` 176줄) | `tests/test_cli.py`, [checklist.md 1-4](checklist.md#1-4-budget-set-이-저장되며-summary-에서-예산-사용률초과-여부가-출력되는가-) | ✅ |
| 5 | CSV 스키마 (`CSV_COLUMNS`) | export/import 후 CSV 헤더와 한 줄 예시 | export 파일 `head -3`, `--bom` 바이트 확인, `.rejected.csv` 실제 내용 | README [실제 파일 예시](../README.md#실제-파일-예시) | ✅ |
| 6 | 원인 + 힌트 오류 출력 (`decorators.py`) | 자주 마주칠 오류의 해결 절차 체크리스트 | 권한 · 손상된 줄 · 저장 실패 · 없는 카테고리 · CSV 헤더/인코딩 · 예기치 못한 오류, 메시지별 ①② 절차 | README [문제 해결](../README.md#문제-해결) | ✅ |
| 7 | 종료 코드 상수 (`errors.py`) | 종료 코드별 쉘 검증 예시를 한 섹션으로 | 코드표에 재현 명령 열 추가, 0 · 2 · 3 · 4 · 5 를 차례로 재현한 `echo $?` 기록 | README [쉘에서 종료 코드 확인하기](../README.md#쉘에서-종료-코드-확인하기) | ✅ |
| 8 | 모듈 계층 분리 (`docs/checklist.md`) | 의존 방향을 검증하는 테스트 실행 명령 안내 | `test_layer_dependency_direction` 실행 명령 | [design.md 1절](design.md#1-계층-구조), README [아키텍처](../README.md#아키텍처) | ✅ |
| 9 | dataclass 모델 (`models.py`) | 모델별 책임 한 줄 요약표 | 모델 6개: 한 줄 책임 · 읽고 쓰는 저장소 · 검증 함수 | [design.md 2절](design.md#모델-클래스-책임-요약-modelspy) | ✅ |
| 10 | 원자적 교체 (`storage.py` `os.replace`) | 다른 파일 시스템 경계 주의사항 | 같은 폴더에 임시 파일을 두는 이유, 심볼릭 링크 · 네트워크/동기화 폴더 · Windows 파일 잠금 주의 | README [수정 · 삭제가 안전한 이유와 주의할 점](../README.md#수정--삭제가-안전한-이유와-주의할-점), [design.md 3.3](design.md#33-안전한-update--delete-원자적-교체--보너스-저장-원자성-강화) | ✅ |
| 11 | 제너레이터 스트리밍 + heapq (`services.py`) | 스트리밍 이점과 시간복잡도 요약 | 명령별 시간 · 메모리 복잡도 표, "스트리밍은 메모리를 줄이지 시간을 줄이지 않는다" | [design.md 4절](design.md#4-제너레이터-스트리밍) | ✅ |
| 12 | 데코레이터 조합 (`decorators.py`) | 데코레이터가 실패했을 때의 정책을 상단 주석으로 | 모듈 docstring 에 데코레이터별 실패 정책, design.md 에 표 | `budget_app/decorators.py` 18~24줄, [design.md 5절](design.md#5-데코레이터-공통-관심사-분리) | ✅ |
| 13 | 타입 힌트 (`services.py`) | CI 에 가벼운 타입 검사(mypy) 추가 | mypy 2.4.1 을 `typecheck` 그룹에 고정, 오류 13건 수정, CI(Ubuntu)에 단계 추가 | `.github/workflows/tests.yml`, `pyproject.toml`, [design.md 6절](design.md#6-타입-힌트) | ✅ |
| 14 | JSONL 선택 근거 (README) | JSONL vs CSV 장단점 표 | 기존 표에 쉼표 · 줄바꿈 처리, append, 파일 크기 행과 결론 추가 | [design.md 3.2](design.md#32-jsonl-을-선택한-이유), [checklist.md 4-1](checklist.md) | ✅ |
| 15 | 10만 건 병목 분석 (`docs/performance.md`) | 개선안별 난이도 · 마이그레이션 주의점 | 개선안 6개의 효과 · 난이도 · 위험 · 데이터 이전 주의, 권장 순서 | [performance.md](performance.md#개선안별-난이도와-데이터-이전-주의점) | ✅ |
| 16 | import 부분 성공 · 거부 행 리포트 (`services.py`) | 거부 행이 많을 때의 요약 출력 전략 | 화면 20건 + "외 N건" / 숫자 요약 / 파일 전체 보존의 3단계 문서화, 25건 거부 테스트 | [design.md 9절](design.md#깨진-행이-섞인-csv-를-가져올-때), `tests/test_cli.py` | ✅ |

## 확인 방법

```bash
python -m unittest discover -s tests -t . -v      # 전체 테스트
python -m unittest tests.test_cli.BudgetThresholdTest tests.test_cli.ImportRejectedSummaryTest -v   # 이번에 추가한 테스트
uv run --group typecheck mypy                      # 타입 검사
```
