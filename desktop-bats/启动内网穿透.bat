@echo off
REM ============================================================
REM  启动内网穿透.bat  (桌面快捷入口, 2026-10-20)
REM  链路: frpc服务(开机自启) + 本地8080网关(model-tee)
REM  本BAT只负责拉起 8080 网关; 公网地址:
REM  http://18c23w6n.zjz-service.cn:28024/v1
REM ============================================================
chcp 65001 >nul
title 启动内网穿透网关

echo [1/3] 清理旧网关...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*model-tee*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
ping -n 4 127.0.0.1 >nul

echo [2/3] 启动网关 8080 (model-tee)...
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'D:\Python312\python.exe' -ArgumentList 'D:\llama-monitor\model-tee.py','8080' -RedirectStandardOutput 'D:\llama\gateway-8080.log' -RedirectStandardError 'D:\llama\gateway-8080.err.log'"

echo [3/3] 健康检查...
set /a tries=0
:wait
set /a tries+=1
if %tries% geq 12 goto report
curl -s -m 3 http://127.0.0.1:8080/health 2>nul | findstr /c:"ok" >nul
if errorlevel 1 (
    ping -n 6 127.0.0.1 >nul
    goto wait
)

:report
echo.
echo ===== 启动结果 =====
curl -s -m 3 http://127.0.0.1:8080/health 2>nul | findstr /c:"ok" >nul && echo [OK] 本地网关 8080 在线 || echo [FAIL] 网关未起, 查 D:\llama\gateway-8080.err.log
sc query FrpembedService 2>nul | findstr /c:"RUNNING" >nul && echo [OK] frp 穿透服务运行中 || echo [FAIL] FrpembedService 未运行, 需手动启动服务
curl -s -m 12 http://18c23w6n.zjz-service.cn:28024/health 2>nul | findstr /c:"ok" >nul && echo [OK] 公网穿透正常 || echo [WARN] 公网不通(隧道延迟或frpc需重启)
echo.
echo 公网地址: http://18c23w6n.zjz-service.cn:28024/v1
ping -n 11 127.0.0.1 >nul
exit /b 0
