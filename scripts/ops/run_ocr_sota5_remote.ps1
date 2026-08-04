param(
    [Parameter(Mandatory = $true)]
    [string]$ModelSlug,
    [int]$Limit = 1,
    [int]$MaxNewTokens = 2048
)

$ErrorActionPreference = "Stop"
$BenchmarkRoot = "F:\ocr_sota5_20260803"
$Python = if ($ModelSlug -eq "mineru_2_5_pro_2605") {
    "$BenchmarkRoot\.venv312\Scripts\python.exe"
} else {
    "F:\bench\.venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found: $Python"
}

$env:HF_HOME = "$BenchmarkRoot\hf_cache"
$env:HUGGINGFACE_HUB_CACHE = "$BenchmarkRoot\hf_cache\hub"
$env:TRANSFORMERS_CACHE = "$BenchmarkRoot\hf_cache\transformers"
$env:TOKENIZERS_PARALLELISM = "false"
$env:PYTHONUTF8 = "1"

$OutputDirectory = "$BenchmarkRoot\output\$ModelSlug"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

& $Python `
    "$BenchmarkRoot\scripts\ocr_sota5_runner.py" `
    --config "$BenchmarkRoot\ocr_sota5_bench.json" `
    --manifest "$BenchmarkRoot\manifest.json" `
    --model $ModelSlug `
    --input-dir "$BenchmarkRoot\input" `
    --output-dir $OutputDirectory `
    --limit $Limit `
    --max-new-tokens $MaxNewTokens

exit $LASTEXITCODE
