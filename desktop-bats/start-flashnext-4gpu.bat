@echo off
title Start FlashNext 4-GPU 8081

echo [1/3] Killing old processes...
powershell -NoProfile -Command "Get-Process strata,python -ErrorAction SilentlyContinue | Where-Object {($_.Path -like *strata*) -or ($_.CommandLine -like *strata*)} | Stop-Process -Force -ErrorAction SilentlyContinue"
ping -n 5 127.0.0.1 >nul

echo [2/3] Starting Flash-Next 4-GPU on port 8081 (load ~3min)...
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath E:\strata-src\.venv\Scripts\python.exe -ArgumentList E:\strata-src\serve\server.py,--engine,strata,--config,E:\strata-src\strata-iq3_s-4gpu.json,--port,8081 -WorkingDirectory E:\strata-src -RedirectStandardOutput D:\llama\strata-4gpu.out.log -RedirectStandardError D:\llama\strata-4gpu.err.log"

echo [3/3] Health check (max 6 minutes)...
set /a tries=0
:wait
set /a tries+=1
if %tries% geq 36 goto report
curl -s -m 3 http://127.0.0.1:8081/health 2>nul | findstr /c:"ok" >nul
if errorlevel 1 (
    ping -n 11 127.0.0.1 >nul
    goto wait
)

:report
echo.
echo ===== Result =====
curl -s -m 3 http://127.0.0.1:8081/health 2>nul | findstr /c:"ok" >nul && echo [OK] 8081 Flash-Next 4-GPU online || echo [FAIL] Check D:\llama\strata-4gpu.err.log
echo Log: D:\llama\strata-4gpu.out.log
ping -n 9 127.0.0.1 >nul
exit /b 0