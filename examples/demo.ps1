# Windows PowerShell 용 데모. 과제 결과 예시 흐름을 임시 데이터 폴더에서 실행한다.
#   powershell -ExecutionPolicy Bypass -File examples\demo.ps1
Set-Location (Join-Path $PSScriptRoot "..")
$data = Join-Path ([System.IO.Path]::GetTempPath()) ("budget-demo-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

function Run { Write-Host "`n> python -m budget_app $args" -ForegroundColor Cyan; python -m budget_app --data-dir $data @args }
function Add-Tx { param([string[]]$Lines) Write-Host "`n> python -m budget_app add" -ForegroundColor Cyan; ($Lines -join "`n") | python -m budget_app --data-dir $data add }

Add-Tx @("2024-01-05", "expense", "rent", "150000", "월세", "fixed")
Add-Tx @("2024-01-10", "expense", "food", "30000", "장보기", "grocery")
Add-Tx @("2024-01-12", "expense", "transport", "20000", "", "")
Add-Tx @("2024-01-14", "income", "salary", "3000000", "월급", "")
Add-Tx @("2024-01-15", "expense", "food", "15000", "점심", "meal")
Run list --limit 3 --plain
Run budget set --month 2024-01 --amount 500000
Run summary --month 2024-01 --top 3
Run search --type expense --tag meal
Run export --out (Join-Path $data "export.csv") --month 2024-01
Run import --from examples\sample_import.csv
Run import --from examples\broken_import.csv --dry-run
Run backup --label demo
Run recurring add --type income --category salary --amount 3000000 --day 25 --memo 월급
Run recurring apply --month 2024-02
Write-Host "`n데이터 폴더: $data"
