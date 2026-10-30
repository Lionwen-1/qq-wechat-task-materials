param([string]$EnvironmentDirectory = "$PSScriptRoot\.venv", [string]$PythonExecutable = 'python')
$ErrorActionPreference = 'Stop'
& $PythonExecutable -c "import sys; assert sys.version_info[:2] == (3, 13) and sys.version_info[:3] >= (3, 13, 18), '请使用 Python 3.13.18 或本分支更新的安全版本'"
if ($LASTEXITCODE -ne 0) { throw 'Python 版本不符合已验证环境' }
& $PythonExecutable -m venv $EnvironmentDirectory
if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败' }
$bridgePython = Join-Path $EnvironmentDirectory 'Scripts\python.exe'
& $bridgePython -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r "$PSScriptRoot\requirements-lock-windows-py313.txt"
if ($LASTEXITCODE -ne 0) { throw '安装依赖失败' }
& $bridgePython "$PSScriptRoot\privacy.py"
if ($LASTEXITCODE -ne 0) { throw '保护本工具目录失败，未完成安装' }
Write-Output "安装完成：$bridgePython"
Write-Output '请按 README 创建本地配置；此步骤没有启动读取或修改任何模型客户端配置。'
