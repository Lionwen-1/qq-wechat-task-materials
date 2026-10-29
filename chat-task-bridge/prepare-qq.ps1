param([string]$Destination = "$PSScriptRoot\qq-backend")
$ErrorActionPreference = 'Stop'
$assetUrl = 'https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.41/NapCat.Shell.Windows.OneKey.zip'
$expectedHash = '46c3ec155aa61f12e89bbf97013a21243d00b0019b5565992a88852d7627f39c'
$absoluteDestination = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $absoluteDestination | Out-Null
$archive = Join-Path $absoluteDestination 'NapCat.Shell.Windows.OneKey-v4.18.41.zip'
if (-not (Test-Path -LiteralPath $archive)) { Invoke-WebRequest -Uri $assetUrl -OutFile $archive }
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw '上游包 SHA256 不匹配，已停止' }
$unpacked = Join-Path $absoluteDestination 'v4.18.41'
if (Test-Path -LiteralPath $unpacked) { throw '目标版本目录已存在；请检查后复用，避免覆盖' }
Expand-Archive -LiteralPath $archive -DestinationPath $unpacked
Write-Output "已下载并校验：$unpacked"
Write-Output '尚未安装或启动。按 NapCat 官方说明使用 NapCatInstaller.exe，登录个人 QQ 后只开回环 HTTP API。'
