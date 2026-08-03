$ErrorActionPreference = "Stop"

$Root = "F:\ocr_sota5_20260803\llamacpp_cuda_b10223"
$MainZip = "$Root\llama-b10223-bin-win-cuda-12.4-x64.zip"
$CudaZip = "$Root\cudart-llama-bin-win-cuda-12.4-x64.zip"
$Release = "https://github.com/ggml-org/llama.cpp/releases/download/b10223"

New-Item -ItemType Directory -Force -Path $Root | Out-Null

if (-not (Test-Path -LiteralPath $MainZip)) {
    Invoke-WebRequest -Uri "$Release/llama-b10223-bin-win-cuda-12.4-x64.zip" -OutFile $MainZip
}
if (-not (Test-Path -LiteralPath $CudaZip)) {
    Invoke-WebRequest -Uri "$Release/cudart-llama-bin-win-cuda-12.4-x64.zip" -OutFile $CudaZip
}

Expand-Archive -LiteralPath $MainZip -DestinationPath $Root -Force
Expand-Archive -LiteralPath $CudaZip -DestinationPath $Root -Force

Get-ChildItem -LiteralPath $Root -Filter "llama-cli.exe" -Recurse | Select-Object -ExpandProperty FullName
