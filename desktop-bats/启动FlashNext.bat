@echo off
REM ============================================================
REM  Start Swift-1.5 IQ3_S on 4 GPUs (port 8081)
REM  4-stage true layer split + pipeline-windows 2, 256K context
REM  decode ~110 t/s (long output), prefill ~1670 t/s @32K
REM  config: E:\strata-src\strata-swift-iq3_s-4gpu.json
REM  notes : see D:\llama-monitor\docs\ (true-split speedup writeup)
REM ============================================================
title Start Swift-1.5 4-GPU 8081

echo [1/3] Killing old processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*strata*server.py*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -NoProfile -Command "Get-Process strata -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
ping -n 5 127.0.0.1 >nul

echo [2/3] Starting 4-GPU engine on 8081 (load ~3-4 min)...
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'E:\strata-src\.venv\Scripts\python.exe' -ArgumentList 'E:\strata-src\serve\server.py','--engine','strata','--config','E:\strata-src\strata-swift-iq3_s-4gpu.json','--port','8081' -WorkingDirectory 'E:\strata-src' -RedirectStandardOutput 'E:\strata-src\strata-4gpu.out.log' -RedirectStandardError 'E:\strata-src\strata-4gpu.err.log'"

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
curl -s -m 3 http://127.0.0.1:8081/health 2>nul | findstr /c:"ok" >nul && echo [OK] 8081 Swift-1.5 4-GPU online (256K) || echo [FAIL] not up, see E:\strata-src\strata-4gpu.err.log
echo Log: E:\strata-src\strata-4gpu.out.log
ping -n 9 127.0.0.1 >nul
exit /b 0
