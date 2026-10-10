# 2026-10-11：本次修改原因：生成开发版副本；添加 UTF-8 BOM 兼容 Windows PowerShell 5.1 中文脚本。
# 2026-10-11：本次修改原因：生成可直接加载的开发版插件副本，不覆盖原插件文件。
param(
    [string]$SourcePath = 'D:\tradeSoftwares\kuajing-erp-plugin-v3-5x (2)',
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$OutputName = 'unpacked'
)
$ErrorActionPreference = 'Stop'
$BeadDiffRoot = Split-Path -Parent $PSScriptRoot
$BranchRoot = Join-Path $BeadDiffRoot 'browser_extension'
$OutputPath = [IO.Path]::GetFullPath((Join-Path $BranchRoot $OutputName))
$SourceResolved = (Resolve-Path -LiteralPath $SourcePath).Path
if (-not (Test-Path -LiteralPath (Join-Path $SourceResolved 'background.js') -PathType Leaf)) {
    throw 'The source folder does not contain background.js.'
}
if (-not $OutputPath.StartsWith(([IO.Path]::GetFullPath($BranchRoot) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output must stay inside the project browser_extension folder.'
}
if (Test-Path -LiteralPath $OutputPath) {
    throw 'Output already exists. Use a new -OutputName; this script never overwrites an existing plugin copy.'
}
$BranchFiles = @('beaddiff-worker.js', 'beaddiff-protocol.js', 'beaddiff-forwarder.js',
                  'beaddiff-options.html', 'beaddiff-options.css', 'beaddiff-options.js')
foreach ($Name in ($BranchFiles + @('manifest.beaddiff.json'))) {
    if (-not (Test-Path -LiteralPath (Join-Path $BranchRoot $Name) -PathType Leaf)) {
        throw "Missing branch file: $Name"
    }
}
$OriginalManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $SourceResolved 'manifest.json') | ConvertFrom-Json
$PatchedManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $BranchRoot 'manifest.beaddiff.json') | ConvertFrom-Json
if ($OriginalManifest.version -ne $PatchedManifest.version -or $OriginalManifest.key -ne $PatchedManifest.key) {
    throw 'The source plugin version/key differs from the prepared manifest. Inspect the new source before preparing a copy.'
}
if ($OriginalManifest.background.service_worker -ne 'background.js') {
    throw 'The source background entry differs from the inspected 5.0.9 plugin.'
}
New-Item -ItemType Directory -Path $OutputPath | Out-Null
foreach ($Entry in (Get-ChildItem -Force -LiteralPath $SourceResolved)) {
    # _metadata 是商店签名校验信息；开发版副本不复制它，原目录中的文件仍保留。
    if ($Entry.Name -notin @('manifest.json', '_metadata')) {
        Copy-Item -LiteralPath $Entry.FullName -Destination $OutputPath -Recurse
    }
}
foreach ($Name in $BranchFiles) {
    Copy-Item -LiteralPath (Join-Path $BranchRoot $Name) -Destination (Join-Path $OutputPath $Name)
}
Copy-Item -LiteralPath (Join-Path $BranchRoot 'manifest.beaddiff.json') -Destination (Join-Path $OutputPath 'manifest.json')
$OriginalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $SourceResolved 'background.js')).Hash
$CopiedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $OutputPath 'background.js')).Hash
if ($OriginalHash -ne $CopiedHash) { throw 'The original background copy failed the SHA256 check.' }
Write-Output "Ready-to-load plugin: $OutputPath"
Write-Output "Original background.js SHA256 preserved: $CopiedHash"
