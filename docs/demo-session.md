# 데모 실행 기록

`bash examples/demo.sh` 를 실제로 실행한 출력입니다 (Windows: `examples\demo.ps1`). 임시 데이터 폴더 경로만 `./data` 로 바꿔 표시했습니다.

```console

$ python -m budget_app add
[안내] 데이터 파일을 만들었습니다: ./data
[안내] 카테고리가 비어 있어 기본 카테고리를 만들었습니다: food, transport, rent, shopping, health, education, culture, salary, allowance, etc
날짜(YYYY-MM-DD, 엔터=오늘): 2024-01-05
타입(income/expense): expense
카테고리: rent
금액(양수): 150000
메모(선택): 월세
태그(쉼표로 구분, 없으면 엔터): fixed
[저장 완료] id=TX-000001

$ python -m budget_app add
날짜(YYYY-MM-DD, 엔터=오늘): 2024-01-10
타입(income/expense): expense
카테고리: food
금액(양수): 30000
메모(선택): 장보기
태그(쉼표로 구분, 없으면 엔터): grocery
[저장 완료] id=TX-000002

$ python -m budget_app add
날짜(YYYY-MM-DD, 엔터=오늘): 2024-01-12
타입(income/expense): expense
카테고리: transport
금액(양수): 20000
메모(선택): 
태그(쉼표로 구분, 없으면 엔터): 
[저장 완료] id=TX-000003

$ python -m budget_app add
날짜(YYYY-MM-DD, 엔터=오늘): 2024-01-14
타입(income/expense): income
카테고리: salary
금액(양수): 3000000
메모(선택): 월급
태그(쉼표로 구분, 없으면 엔터): 
[저장 완료] id=TX-000004

$ python -m budget_app add
날짜(YYYY-MM-DD, 엔터=오늘): 2024-01-15
타입(income/expense): expense
카테고리: food
금액(양수): 15000
메모(선택): 점심
태그(쉼표로 구분, 없으면 엔터): meal
[저장 완료] id=TX-000005

$ python -m budget_app list --limit 3 --plain
TX-000005 | 2024-01-15 | expense | food | 15000 | 점심
TX-000004 | 2024-01-14 | income  | salary | 3000000 | 월급
TX-000003 | 2024-01-12 | expense | transport | 20000 |
(exit 0)

$ python -m budget_app list
ID         날짜        타입     카테고리          금액  메모    태그
---------  ----------  -------  ---------  -----------  ------  --------
TX-000005  2024-01-15  expense  food          15,000원  점심    #meal
TX-000004  2024-01-14  income   salary     3,000,000원  월급
TX-000003  2024-01-12  expense  transport     20,000원
TX-000002  2024-01-10  expense  food          30,000원  장보기  #grocery
TX-000001  2024-01-05  expense  rent         150,000원  월세    #fixed
(최신순 5건)
(exit 0)

$ python -m budget_app category add cafe
[저장 완료] category=cafe
(exit 0)

$ python -m budget_app category list
- food (2건)
- transport (1건)
- rent (1건)
- shopping
- health
- education
- culture
- salary (1건)
- allowance
- etc
- cafe
(exit 0)

$ python -m budget_app budget set --month 2024-01 --amount 500000
[저장 완료] 2024-01 예산 500,000원
(exit 0)

$ python -m budget_app summary --month 2024-01 --top 3
[2024-01 월별 요약]
총 수입: 3,000,000원
총 지출: 215,000원
잔액: 2,785,000원
예산: 500,000원 (사용률 43.0%) [#########...........]
남은 예산: 285,000원

지출 TOP 3
1)  rent       150,000원  69.8%
2)  food        45,000원  20.9%
3)  transport   20,000원   9.3%
(exit 0)

$ python -m budget_app search --from 2024-01-01 --to 2024-01-31 --type expense --tag meal
ID         날짜        타입     카테고리      금액  메모  태그
---------  ----------  -------  --------  --------  ----  -----
TX-000005  2024-01-15  expense  food      15,000원  점심  #meal
(검색 결과 1건 · 수입 0원 · 지출 15,000원)
(exit 0)

$ python -m budget_app update --id TX-000005 --amount 18000 --memo 점심(회식)
[수정 완료] TX-000005
  amount: 15000 -> 18000
  memo: 점심 -> 점심(회식)
(exit 0)

$ python -m budget_app delete --id TX-000003
[삭제 완료] TX-000003 2024-01-12 expense transport 20,000원
(exit 0)

$ python -m budget_app delete --id TX-000003
[오류] id=TX-000003 거래를 찾을 수 없습니다.
[힌트] list 또는 search 로 id 를 확인하세요.
(exit 3)

$ python -m budget_app export --out export.csv --month 2024-01
[완료] export.csv (4 records)
(exit 0)

$ python -m budget_app import --from examples/sample_import.csv
[완료] imported=5, skipped=0
(exit 0)

$ python -m budget_app import --from examples/broken_import.csv --atomic
[건너뜀] 3번째 줄: 존재하지 않는 날짜입니다: 2024-02-30
[건너뜀] 4번째 줄: 등록되지 않은 카테고리: unknown
[건너뜀] 5번째 줄: 금액은 0보다 커야 합니다: -100
[건너뜀] 6번째 줄: 허용되지 않는 타입입니다: refund
[롤백] 오류가 있어 아무것도 가져오지 않았습니다: imported=0, skipped=4
[힌트] 거부된 행과 사유: examples/broken_import.rejected.csv
(exit 2)

$ python -m budget_app import --from examples/broken_import.csv --dry-run
[건너뜀] 3번째 줄: 존재하지 않는 날짜입니다: 2024-02-30
[건너뜀] 4번째 줄: 등록되지 않은 카테고리: unknown
[건너뜀] 5번째 줄: 금액은 0보다 커야 합니다: -100
[건너뜀] 6번째 줄: 허용되지 않는 타입입니다: refund
[검증] 가져올 수 있는 행 2건, 오류 4건 — 저장하지 않았습니다 (--dry-run)
(exit 2)

$ python -m budget_app category remove food
[오류] 카테고리 'food' 는 거래 3건에서 사용 중이라 삭제할 수 없습니다.
[힌트] --replace-with <다른 카테고리> 를 지정하면 거래를 옮긴 뒤 삭제합니다.
(exit 4)

$ python -m budget_app category remove food --replace-with etc
[삭제 완료] category=food (거래 3건을 'etc' 로 옮김)
(exit 0)

$ python -m budget_app backup --label demo
[백업 완료] ./data/backups/backup-20261012-141922-demo.zip
(exit 0)

$ python -m budget_app recurring add --type income --category salary --amount 3000000 --day 25 --memo 월급
[저장 완료] id=RC-0001 (매달 25일 income salary 3,000,000원)
(exit 0)

$ python -m budget_app recurring add --type expense --category rent --amount 500000 --day 31 --memo 월세
[저장 완료] id=RC-0002 (매달 31일 expense rent 500,000원)
(exit 0)

$ python -m budget_app recurring apply --month 2024-02
[생성] TX-000011 2024-02-25 income salary 3,000,000원 월급
[생성] TX-000012 2024-02-29 expense rent 500,000원 월세
[완료] 2024-02 반복 내역 created=2, skipped=0
(exit 0)

$ python -m budget_app recurring apply --month 2024-02
[완료] 2024-02 반복 내역 created=0, skipped=2 (이미 생성됨: RC-0001, RC-0002)
(exit 0)

$ python -m budget_app summary --month 2024-02
[2024-02 월별 요약]
총 수입: 3,050,000원
총 지출: 560,250원
잔액: 2,489,750원
예산: 미설정 (budget set --month 2024-02 --amount <금액>)

지출 TOP 3
1)  rent      500,000원  89.2%
2)  shopping   32,000원   5.7%
3)  culture    15,000원   2.7%
(exit 0)
```
