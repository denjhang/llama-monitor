@echo off
rem 监控台启动器：已有实例先关再启（相当于重启），pythonw 无窗口
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name=%27python.exe%27 or Name=%27pythonw.exe%27\" | Where-Object {$_.CommandLine -like %27*monitor_gui.py*%27} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
ping -n 2 127.0.0.1 >nul
start "" /min pythonw D:\llama-monitor\monitor_gui.py
echo 监控台已启动（D:\llama-monitor\monitor_gui.py）
