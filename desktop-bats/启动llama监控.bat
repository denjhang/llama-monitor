@echo off
title Start llama-monitor GUI

echo [1/2] Killing old monitor instances...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | Where-Object {$_.CommandLine -like '*monitor_gui.py*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
ping -n 3 127.0.0.1 >nul

echo [2/2] Starting monitor GUI (pythonw, no console)...
powershell -NoProfile -Command "Start-Process -FilePath 'D:\Python312\pythonw.exe' -ArgumentList 'D:\llama-monitor\monitor_gui.py' -WorkingDirectory 'D:\llama-monitor'"
ping -n 4 127.0.0.1 >nul

echo.
echo ===== Result =====
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object {$_.CommandLine -like '*monitor_gui.py*'}) { Write-Host '[OK] monitor GUI running' } else { Write-Host '[FAIL] monitor_gui.py not running' }"
ping -n 6 127.0.0.1 >nul
exit /b 0
