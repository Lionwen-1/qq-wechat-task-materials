param([string]$Destination = "$PSScriptRoot\.python")
$ErrorActionPreference = 'Stop'
$runtimeDirectory = [IO.Path]::GetFullPath($Destination)
if ($runtimeDirectory.TrimEnd('\') -eq [IO.Path]::GetPathRoot($runtimeDirectory).TrimEnd('\')) {
    throw '不能把磁盘根目录作为程序运行环境'
}
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
if ((Get-Item -LiteralPath $runtimeDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw '运行环境目录不能是目录联接或符号链接'
}
# Restrict this tool-owned directory before downloading or extracting executables.
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
foreach ($targetDirectory in @($runtimeDirectory, $PSScriptRoot)) {
    $runtimeAcl = [Security.AccessControl.DirectorySecurity]::new()
    $runtimeAcl.SetAccessRuleProtection($true, $false)
    foreach ($runtimeSid in @($ownerSid, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'), [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new($runtimeSid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $runtimeAcl.AddAccessRule($rule)
    }
    $directoryInfo = [IO.DirectoryInfo]::new($targetDirectory)
    if ('System.IO.FileSystemAclExtensions' -as [type]) {
        [IO.FileSystemAclExtensions]::SetAccessControl($directoryInfo, $runtimeAcl)
    } else {
        $directoryInfo.SetAccessControl($runtimeAcl)
    }
}
$runtimePython = Join-Path $runtimeDirectory 'python\python.exe'
if (Test-Path -LiteralPath $runtimePython) {
    & $runtimePython -c "import sys; assert sys.version_info[:3] == (3, 13, 18)"
    if ($LASTEXITCODE -ne 0) { throw '目录中已有其他版本，请使用本工具的新空目录' }
    return $runtimePython
}
if ((Get-ChildItem -LiteralPath $runtimeDirectory -Force | Measure-Object).Count -gt 0) {
    throw '运行环境目录不是空目录，未覆盖任何已有文件'
}
$archivePath = Join-Path $runtimeDirectory 'python.tar.gz'
$downloadUrl = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
$expectedHash = '7369f7a35f261222a6ac8b3a87c1c88eeebee8af945d85346202591a64038dd3'
Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    Remove-Item -LiteralPath $archivePath -Force
    throw 'Python运行环境哈希不符，未执行或解压'
}
& tar -xzf $archivePath -C $runtimeDirectory
if ($LASTEXITCODE -ne 0) { throw '解压Python运行环境失败' }
Remove-Item -LiteralPath $archivePath -Force
& $runtimePython -c "import sys; assert sys.version_info[:3] == (3, 13, 18)"
if ($LASTEXITCODE -ne 0) { throw 'Python版本校验失败' }
& $runtimePython -m ensurepip --upgrade | Write-Host
if ($LASTEXITCODE -ne 0) { throw '准备pip失败' }
return $runtimePython
