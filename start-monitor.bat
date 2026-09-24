@echo off
rem 监控台启动器：已有实例先关再启（相当于重启），pythonw 无窗口
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | Where-Object {$_.CommandLine -like '*monitor_gui.py*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
ping -n 2 127.0.0.1 >nul
start "" /min pythonw E:\working\llama-cpp\llama\monitor_gui.py
echo 监控台已启动（monitor_gui.py）
