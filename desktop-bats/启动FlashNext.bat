@echo off
REM ============================================================
REM  启动FlashNext.bat  (桌面快捷入口, 2026-10-20)
REM  8081 Flash-Next IQ3_S (Strata 双卡 GPU0/1, 原生256K, 66-75 t/s)
REM ============================================================
chcp 65001 >nul
title 启动 Flash-Next 8081

echo [1/3] 清理旧进程...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*strata*server.py*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -NoProfile -Command "Get-Process strata -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
ping -n 4 127.0.0.1 >nul

echo [2/3] 启动 Flash-Next 8081 (Strata, 原生256K, 加载约2分钟)...
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'E:\strata-src\.venv\Scripts\python.exe' -ArgumentList 'E:\strata-src\serve\server.py','--engine','strata','--config','E:\strata-src\strata-iq3_s.json','--port','8081' -WorkingDirectory 'E:\strata-src' -RedirectStandardOutput 'D:\llama\strata-iq3s.out.log' -RedirectStandardError 'D:\llama\strata-iq3s.err.log'"

echo [3/3] 健康检查 (最长5分钟)...
set /a tries=0
:wait
set /a tries+=1
if %tries% geq 30 goto report
curl -s -m 3 http://127.0.0.1:8081/health 2>nul | findstr /c:"ok" >nul
if errorlevel 1 (
    ping -n 11 127.0.0.1 >nul
    goto wait
)

:report
echo.
echo ===== 启动结果 =====
curl -s -m 3 http://127.0.0.1:8081/health 2>nul | findstr /c:"ok" >nul && echo [OK] 8081 Flash-Next 在线 (256K) || echo [FAIL] 未起, 查 D:\llama\strata-iq3s.err.log
ping -n 9 127.0.0.1 >nul
exit /b 0
