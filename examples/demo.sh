#!/usr/bin/env bash
# 과제 결과 예시 흐름을 처음부터 끝까지 실행한다. (임시 데이터 폴더 사용)
#   bash examples/demo.sh
set -u
cd "$(dirname "$0")/.."
DATA="$(mktemp -d)/data"
run() { echo; echo "\$ python -m budget_app $*"; python -m budget_app --data-dir "$DATA" "$@"; echo "(exit $?)"; }
add() { echo; echo "\$ python -m budget_app add"; printf '%s\n' "$@" | python -m budget_app --data-dir "$DATA" add; }

add 2024-01-05 expense rent 150000 월세 fixed
add 2024-01-10 expense food 30000 장보기 grocery
add 2024-01-12 expense transport 20000 "" ""
add 2024-01-14 income salary 3000000 월급 ""
add 2024-01-15 expense food 15000 점심 meal
run list --limit 3 --plain
run list
run category add cafe
run category list
run budget set --month 2024-01 --amount 500000
run summary --month 2024-01 --top 3
run search --from 2024-01-01 --to 2024-01-31 --type expense --tag meal
run update --id TX-000005 --amount 18000 --memo "점심(회식)"
run delete --id TX-000003
run delete --id TX-000003
run export --out "$DATA/../export.csv" --month 2024-01
run import --from examples/sample_import.csv
run import --from examples/broken_import.csv --atomic
run import --from examples/broken_import.csv --dry-run
run category remove food
run category remove food --replace-with etc
run backup --label demo
run recurring add --type income --category salary --amount 3000000 --day 25 --memo 월급
run recurring add --type expense --category rent --amount 500000 --day 31 --memo 월세
run recurring apply --month 2024-02
run recurring apply --month 2024-02
run summary --month 2024-02
