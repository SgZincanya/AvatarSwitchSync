param(
    [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    [string]$InnoCompiler = '',
    [switch]$SkipInstaller
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
        throw '请先创建 .venv 并安装 requirements-dev.txt，或通过 -Python 指定 Python 3.12 的路径。'
    }
    & $Python -m unittest discover -s tests -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw '测试未通过，已停止构建。' }
    $version = & $Python tools\version_resource.py build\version_info.txt
    if ($LASTEXITCODE -ne 0) { throw '生成版本资源失败。' }
    $versionFile = (Resolve-Path build\version_info.txt).Path
    $iconFile = (Resolve-Path src\app.ico).Path
    & $Python -m PyInstaller --noconfirm --windowed --onedir --name AvatarSwitchSync --distpath dist --workpath build\pyinstaller --specpath build --paths src --collect-all zeroconf --icon $iconFile --version-file $versionFile src\avatar_sync.py
    if ($LASTEXITCODE -ne 0) { throw '程序构建失败。' }
    $release = Join-Path $PSScriptRoot 'dist\AvatarSwitchSync'
    New-Item -ItemType Directory -Path (Join-Path $release 'source') -Force | Out-Null
    Copy-Item -LiteralPath src\app.ico,docs\README.md,THIRD_PARTY_NOTICES.md -Destination $release
    Copy-Item -Path src\*.py -Destination (Join-Path $release 'source')
    Copy-Item -LiteralPath requirements.txt -Destination (Join-Path $release 'source')
    Copy-Item -LiteralPath licenses -Destination $release -Recurse -Force
    if (-not $SkipInstaller) {
        if (-not $InnoCompiler) {
            $compilerCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
            if ($compilerCommand) { $InnoCompiler = $compilerCommand.Source }
            else {
                foreach ($compilerPath in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 7\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe")) {
                    if (Test-Path -LiteralPath $compilerPath) { $InnoCompiler = $compilerPath; break }
                }
            }
        }
        if (-not $InnoCompiler) { throw '未找到 Inno Setup；请用 -InnoCompiler 指定 ISCC.exe，或使用 -SkipInstaller 只构建程序。' }
        & $InnoCompiler /Q "/DAppVersion=$version" installer\AvatarSwitchSync.iss
        if ($LASTEXITCODE -ne 0) { throw '安装包构建失败。' }
    }
    Write-Output "构建完成：$PSScriptRoot\dist"
}
finally { Pop-Location }
