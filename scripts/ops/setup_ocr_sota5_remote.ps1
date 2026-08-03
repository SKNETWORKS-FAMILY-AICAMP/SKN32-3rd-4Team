$ErrorActionPreference = "Stop"

$BenchmarkRoot = "F:\ocr_sota5_20260803"
$Directories = @(
    $BenchmarkRoot,
    "$BenchmarkRoot\input",
    "$BenchmarkRoot\scripts",
    "$BenchmarkRoot\output",
    "$BenchmarkRoot\logs",
    "$BenchmarkRoot\hf_cache"
)

foreach ($Directory in $Directories) {
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
}

Write-Output $BenchmarkRoot
