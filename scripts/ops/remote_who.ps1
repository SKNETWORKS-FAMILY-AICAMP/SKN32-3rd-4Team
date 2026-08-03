# ★이 파일은 **UTF-8 BOM** 으로 저장한다.
#   Windows PowerShell 5.1 은 BOM 이 없으면 .ps1 을 ANSI 로 읽어 한글이 깨지고
#   문자열 종결자를 못 찾아 파서 오류가 난다(실측 2026-08-03).
# 공용 GPU 상자에서 **누가 무엇을 돌리고 있나** (RULE.md §3.5)
#
# 쓰는 법 (이 노트북에서):
#   scp scripts/ops/remote_who.ps1 Yeon@10.20.20.1:C:/pagejob/
#   ssh Yeon@10.20.20.1 "powershell -NoProfile -ExecutionPolicy Bypass -File C:\pagejob\remote_who.ps1"
#
# ★그 상자는 여러 세션이 함께 쓴다. 확인 없이 코어를 다 잡으면 남의 작업을 굶긴다.
#   실제로 2026-08-03, 다른 세션이 `bench_embedders --model Qwen/Qwen3-Embedding-4B` 를
#   돌리는 중에 페이지 추출을 12프로세스로 넣을 뻔했다.

Write-Output "== python 프로세스 =="
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
if (-not $procs) {
    Write-Output "  (없음 — 비어 있다)"
} else {
    $procs | ForEach-Object {
        $mb = [math]::Round($_.WorkingSetSize / 1MB)
        "  {0,-7} {1}  {2,6} MB  {3}" -f $_.ProcessId, $_.CreationDate, $mb, $_.CommandLine
    }
}

Write-Output ""
Write-Output "== CPU / GPU =="
$cpu = (Get-CimInstance Win32_Processor)
"  CPU  {0}  논리 {1}코어" -f $cpu.Name, $env:NUMBER_OF_PROCESSORS
try {
    $g = & nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader
    "  GPU  $g"
} catch {
    "  GPU  nvidia-smi 없음"
}

Write-Output ""
Write-Output "★몫을 정할 때: 남이 CPU 를 쓰고 있으면 --jobs 를 낮춘다. 비어 있으면 --jobs 0."
Write-Output "★비율은 눈대중이 아니라 처리량 실측으로 나눈다 (RULE.md §3.5)."
