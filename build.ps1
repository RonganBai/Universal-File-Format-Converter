# 一键构建：PyInstaller 打包 exe → Inno Setup 生成安装包
# 用法：powershell -ExecutionPolicy Bypass -File .\build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$out = Join-Path $env:LOCALAPPDATA "FormatConverter_build"   # 构建目录放在 OneDrive 之外

python -m pip install -r requirements.txt

pyinstaller --noconfirm --windowed --name "FormatConverter" `
    --icon "$root\assets\icon.ico" --add-data "$root\assets;assets" `
    --hidden-import vector --collect-all pillow_heif --collect-data docx --collect-all av `
    --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets `
    --exclude-module PyQt6.QtPdf --exclude-module PyQt6.Qt3DCore --exclude-module tkinter `
    --workpath "$out\work" --specpath "$out\work" --distpath "$out\dist" app.py
if ($LASTEXITCODE) { throw "PyInstaller 失败" }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "未找到 Inno Setup 6：winget install JRSoftware.InnoSetup" }
& $iscc /Qp "/DDistDir=$out\dist\FormatConverter" "$root\installer\FormatConverter.iss"
if ($LASTEXITCODE) { throw "Inno Setup 失败" }
Write-Host "完成：安装包在 installer\Output\" -ForegroundColor Green
