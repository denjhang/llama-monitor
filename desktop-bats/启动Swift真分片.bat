@echo off
REM ============================================================
REM  启动Swift真分片.bat  (桌面快捷入口, 2026-11-02)
REM  Swift-1.5 IQ3_S 四卡四段真分片 + pipeline-windows 2
REM  8081, 256K, decode ~110 t/s (长输出), prefill ~1670 t/s @32K
REM  配置: E:\strata-src\strata-swift-iq3_s-4gpu.json
REM  定论: D:\llama-monitor\docs\Strata-四卡真分片提速定论.md
REM ============================================================
chcp 65001 >nul
title Swift-1.5 真分片 4-GPU 8081

echo [1/3] 清理旧进程...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | Where-Object {$_.CommandLine -like '*strata*server.py*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Get-Process strata -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"
ping -n 5 127.0.0.1 >nul

echo [2/3] 启动四卡引擎 8081 (加载约 3-4 分钟)...
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'E:\strata-src\.venv\Scripts\python.exe' -ArgumentList 'E:\strata-src\serve\server.py','--engine','strata','--config','E:\strata-src\strata-swift-iq3_s-4gpu.json','--port','8081' -WorkingDirectory 'E:\strata-src' -RedirectStandardOutput 'E:\strata-src\strata-4gpu.out.log' -RedirectStandardError 'E:\strata-src\strata-4gpu.err.log'"

echo [3/3] 健康检查 (最长 6 分钟)...
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
echo ===== 启动结果 =====
curl -s -m 3 http://127.0.0.1:8081/health 2>nul | findstr /c:"ok" >nul && echo [OK] 8081 Swift-1.5 真分片在线 (256K) || echo [FAIL] 未起, 查 E:\strata-src\strata-4gpu.err.log
echo 日志: E:\strata-src\strata-4gpu.out.log
ping -n 9 127.0.0.1 >nul
exit /b 0
