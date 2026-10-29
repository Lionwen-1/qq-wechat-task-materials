param([string]$EnvironmentDirectory = "$PSScriptRoot\.venv")
$ErrorActionPreference = 'Stop'
python -c "import sys; assert sys.version_info[:2] == (3, 10), '此锁文件验证环境为 Python 3.10，请切换解释器或单独重新验证依赖'"
if ($LASTEXITCODE -ne 0) { throw 'Python 版本不符合已验证环境' }
python -m venv $EnvironmentDirectory
if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败' }
$bridgePython = Join-Path $EnvironmentDirectory 'Scripts\python.exe'
& $bridgePython -m pip install --disable-pip-version-check -r "$PSScriptRoot\requirements-lock-windows-py310.txt"
if ($LASTEXITCODE -ne 0) { throw '安装依赖失败' }
Write-Output "安装完成：$bridgePython"
Write-Output '请按 README 创建本地配置；此步骤没有启动读取或修改任何模型客户端配置。'
