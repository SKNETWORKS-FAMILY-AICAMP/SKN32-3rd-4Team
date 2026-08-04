param(
    [int]$MaxTokens = 2048
)

$ErrorActionPreference = "Stop"
$Root = "F:\ocr_sota5_20260803"
$Llama = "$Root\llamacpp_cuda_b10223\llama-cli.exe"
$Image = "$Root\input\kcd_gold_heungkukfire_p109.png"
$Output = "$Root\output\paddleocr_vl_1_6_gguf"

if (-not (Test-Path -LiteralPath $Llama)) {
    throw "llama-cli not found: $Llama"
}
if (-not (Test-Path -LiteralPath $Image)) {
    throw "input image not found: $Image"
}

New-Item -ItemType Directory -Force -Path $Output | Out-Null
$env:HF_HOME = "$Root\hf_cache_gguf"

$Started = Get-Date
& $Llama `
    -hf "PaddlePaddle/PaddleOCR-VL-1.6-GGUF" `
    --image $Image `
    -p "Table Recognition:" `
    -n $MaxTokens `
    --temp 0 `
    --no-display-prompt `
    2>&1 | Tee-Object -FilePath "$Output\raw.log"
$ExitCode = $LASTEXITCODE
$Elapsed = ((Get-Date) - $Started).TotalSeconds

@{
    exit_code = $ExitCode
    elapsed_seconds = [Math]::Round($Elapsed, 3)
    max_tokens = $MaxTokens
    model = "PaddlePaddle/PaddleOCR-VL-1.6-GGUF"
    image = "kcd_gold_heungkukfire_p109.png"
} | ConvertTo-Json | Set-Content -LiteralPath "$Output\run.json" -Encoding UTF8

exit $ExitCode
