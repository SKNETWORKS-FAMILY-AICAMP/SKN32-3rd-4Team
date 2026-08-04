$ErrorActionPreference = "Stop"

$BenchmarkRoot = "F:\ocr_shadow48_20260803"
$Directories = @(
    $BenchmarkRoot,
    "$BenchmarkRoot\input",
    "$BenchmarkRoot\scripts",
    "$BenchmarkRoot\output",
    "$BenchmarkRoot\logs"
)

foreach ($Directory in $Directories) {
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
}

Write-Output $BenchmarkRoot

