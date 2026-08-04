param(
    [int]$Limit = 0,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$BenchmarkRoot = "F:\ocr_shadow48_20260803"
$PriorRoot = "F:\ocr_sota5_20260803"
$Python = "$PriorRoot\.venv312\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "MinerU Python environment not found: $Python"
}

$env:HF_HOME = "$PriorRoot\hf_cache"
$env:HUGGINGFACE_HUB_CACHE = "$PriorRoot\hf_cache\hub"
$env:TRANSFORMERS_CACHE = "$PriorRoot\hf_cache\transformers"
$env:TOKENIZERS_PARALLELISM = "false"
$env:PYTHONUTF8 = "1"

$Arguments = @(
    "$BenchmarkRoot\scripts\ocr_sota5_runner.py",
    "--config", "$BenchmarkRoot\ocr_shadow48_bench.json",
    "--manifest", "$BenchmarkRoot\manifest.json",
    "--model", "mineru_2_5_pro_2605",
    "--input-dir", "$BenchmarkRoot\input",
    "--output-dir", "$BenchmarkRoot\output\mineru_2_5_pro_2605",
    "--limit", "$Limit",
    "--seed", "0"
)
if ($Resume) {
    $Arguments += "--resume"
}

& $Python @Arguments
exit $LASTEXITCODE

