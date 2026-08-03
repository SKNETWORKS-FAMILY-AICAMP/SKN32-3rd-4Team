param(
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$PriorRoot = "F:\ocr_sota5_20260803"
$BatchRoot = "F:\s7_prod0"
$Python = "$PriorRoot\.venv312\Scripts\python.exe"
$Runner = "C:\pagejob\ocr_sota5_runner.py"

foreach ($Required in @($Python, $Runner, "$BatchRoot\manifest.json", "$BatchRoot\ocr_config.json")) {
    if (-not (Test-Path -LiteralPath $Required)) {
        throw "Required S7 OCR input not found: $Required"
    }
}

$env:HF_HOME = "$PriorRoot\hf_cache"
$env:HUGGINGFACE_HUB_CACHE = "$PriorRoot\hf_cache\hub"
$env:TRANSFORMERS_CACHE = "$PriorRoot\hf_cache\transformers"
$env:TOKENIZERS_PARALLELISM = "false"
$env:PYTHONUTF8 = "1"

$Arguments = @(
    $Runner,
    "--config", "$BatchRoot\ocr_config.json",
    "--manifest", "$BatchRoot\manifest.json",
    "--model", "mineru_2_5_pro_2605",
    "--input-dir", "$BatchRoot\images",
    "--output-dir", "F:\s7_prod0_output",
    "--limit", "0",
    "--seed", "0"
)
if ($Resume) {
    $Arguments += "--resume"
}

& $Python @Arguments
exit $LASTEXITCODE
