@echo off
REM ============================================================
REM  启动星火治疗版.bat  (桌面快捷入口, 2026-10-20)
REM  8083 Spark-therapy v3h Q6_K (llama.cpp 单卡 GPU4, 256K, 100-114 t/s)
REM  无draft定版(2026-10-20实测: 投机解码对4B小模型无收益)
REM ============================================================
chcp 65001 >nul
title 启动星火治疗版 8083

echo [1/3] 清理旧进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8083 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1
ping -n 4 127.0.0.1 >nul

echo [2/3] 启动星火治疗版 8083 (Q6_K, 256K, 加载约40秒)...
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'D:\llama\llama-server.exe' -ArgumentList '-m','D:/working/spark-therapy/spark-therapy-v3h-q6_k.gguf','--device','CUDA4','-ngl','99','-c','262144','--parallel','1','-ub','1024','-b','1024','-ctk','q4_0','-ctv','q4_0','-fa','on','--metrics','-np','1','--jinja','--temp','0.6','--top-p','0.95','--top-k','20','--alias','spark-therapy-v3h','--host','0.0.0.0','--port','8083' -RedirectStandardOutput 'D:\llama\server-xinghuo-v3h.log' -RedirectStandardError 'D:\llama\server-xinghuo-v3h.err.log'"

echo [3/3] 健康检查 (最长3分钟)...
set /a tries=0
:wait
set /a tries+=1
if %tries% geq 18 goto report
curl -s -m 3 http://127.0.0.1:8083/health 2>nul | findstr /c:"ok" >nul
if errorlevel 1 (
    ping -n 11 127.0.0.1 >nul
    goto wait
)

:report
echo.
echo ===== 启动结果 =====
curl -s -m 3 http://127.0.0.1:8083/health 2>nul | findstr /c:"ok" >nul && echo [OK] 8083 星火治疗版 在线 (256K) || echo [FAIL] 未起, 查 D:\llama\server-xinghuo-v3h.err.log
ping -n 9 127.0.0.1 >nul
exit /b 0
