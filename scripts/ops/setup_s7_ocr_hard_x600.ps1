$ErrorActionPreference = "Stop"

$Packet = "F:\s7_prod0_packet.zip"
$Target = "F:\s7_prod0"
$Python = "F:\ocr_sota5_20260803\.venv312\Scripts\python.exe"

foreach ($Required in @($Packet, $Python)) {
    if (-not (Test-Path -LiteralPath $Required)) {
        throw "Required S7 OCR setup input not found: $Required"
    }
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
& $Python -m zipfile -e $Packet $Target
if ($LASTEXITCODE -ne 0) {
    throw "S7 OCR packet extraction failed with exit $LASTEXITCODE"
}

$ImageCount = @(Get-ChildItem -LiteralPath "$Target\images" -Filter "*.png").Count
if ($ImageCount -ne 1000) {
    throw "Expected 1000 extracted images, got $ImageCount"
}
Write-Output "extracted_images=$ImageCount"
