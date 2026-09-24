$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
$icon = Join-Path $PSScriptRoot "assets\misfondos.ico"
$logo = Join-Path $PSScriptRoot "assets\misfondos.png"
& $venvPython -m PyInstaller --noconfirm --onefile --windowed --name MisFondos `
    --icon $icon `
    --add-data "$icon;assets" `
    --add-data "$logo;assets" `
    --collect-data customtkinter `
    --hidden-import pystray._win32 `
    --distpath "$PSScriptRoot\dist" --workpath "$PSScriptRoot\build" "$PSScriptRoot\run.py"
