param([string]$EnvironmentDirectory = "$PSScriptRoot\.venv", [string]$PythonExecutable = 'python')
$ErrorActionPreference = 'Stop'
$runtimeReady = $false
try {
    & $PythonExecutable -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) and sys.version_info[:3] >= (3, 13, 18) else 1)" 2>$null
    $runtimeReady = $LASTEXITCODE -eq 0
} catch { $runtimeReady = $false }
if (-not $runtimeReady) {
    $PythonExecutable = & "$PSScriptRoot\install-python.ps1"
}
if (Test-Path -LiteralPath (Join-Path $EnvironmentDirectory 'pyvenv.cfg')) {
    & (Join-Path $EnvironmentDirectory 'Scripts\python.exe') -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) and sys.version_info[:3] >= (3, 13, 18) else 1)"
    if ($LASTEXITCODE -ne 0) { throw '原环境版本过旧，请通过EnvironmentDirectory指定新的本工具环境目录；未删除旧环境' }
}
& $PythonExecutable -m venv $EnvironmentDirectory
if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败' }
$bridgePython = Join-Path $EnvironmentDirectory 'Scripts\python.exe'
& $bridgePython -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r "$PSScriptRoot\requirements-lock-windows-py313.txt"
if ($LASTEXITCODE -ne 0) { throw '安装依赖失败' }
& $bridgePython "$PSScriptRoot\privacy.py"
if ($LASTEXITCODE -ne 0) { throw '保护本工具目录失败，未完成安装' }
Write-Output "安装完成：$bridgePython"
Write-Output '请按 README 创建本地配置；此步骤没有启动读取或修改任何模型客户端配置。'
