$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\create_icon.py"
$buildOriginalPath = $env:PATH
$env:PATH = "$env:WINDIR\System32;$env:WINDIR;$PSScriptRoot\.venv\Scripts"
try {
& "$PSScriptRoot\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --distpath "$PSScriptRoot\build\release" --name SeerGallery --icon "$PSScriptRoot\app\assets\app.ico" --add-data "$PSScriptRoot\app\assets;assets" --collect-all UnityPy --collect-all texture2ddecoder --collect-all astc_encoder --collect-all etcpak --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick "$PSScriptRoot\app\main.py"
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
} finally {
    $env:PATH = $buildOriginalPath
}
# Update program files without recursively removing the user's output folder.
New-Item -ItemType Directory -Path "$PSScriptRoot\dist\SeerGallery" -Force | Out-Null
Copy-Item -Path "$PSScriptRoot\build\release\SeerGallery\*" -Destination "$PSScriptRoot\dist\SeerGallery" -Recurse -Force
Copy-Item -LiteralPath "$PSScriptRoot\README.md" -Destination "$PSScriptRoot\dist\SeerGallery\使用说明.md" -Force
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\package_notices.py"
