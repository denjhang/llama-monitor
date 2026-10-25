@echo off
REM ============================================================
REM  启动35B治疗版.bat  (桌面快捷入口, 2026-10-20)
REM  8085 Qwen36-35B-A3B 治疗版 (ik_llama 双卡 GPU2/3, 256K YaRN, 101-112 t/s)
REM ============================================================
chcp 65001 >nul
title 启动 35B 治疗版 8085

echo [1/3] 清理旧进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8085 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1
ping -n 4 127.0.0.1 >nul

echo [2/3] 启动 35B 治疗版 8085 (256K, 加载约1分钟)...
powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'D:\llama-ik\build\bin\llama-server.exe' -ArgumentList '-m','E:/models/nerkyor/Qwen3.6-35B-A3B-DSV4Pro-Thinking-Distill/Q5_K_M.gguf','--mmproj','E:/models/nerkyor/Qwen3.6-35B-A3B-DSV4Pro-Thinking-Distill/mmproj-F16.gguf','--device','CUDA2,CUDA3','-ngl','99','-c','262144','--parallel','1','-ub','2048','-b','8192','-ctk','q4_0','-ctv','q4_0','-fa','on','--temp','0.6','--top-p','0.95','--metrics','--jinja','--alias','qwen3.6-35b-therapy','--host','0.0.0.0','--port','8085' -RedirectStandardOutput 'D:\llama\server-qwen36-35b.log' -RedirectStandardError 'D:\llama\server-qwen36-35b.err.log'"

echo [3/3] 健康检查 (最长2分钟)...
set /a tries=0
:wait
set /a tries+=1
if %tries% geq 12 goto report
curl -s -m 3 http://127.0.0.1:8085/health 2>nul | findstr /c:"ok" >nul
if errorlevel 1 (
    ping -n 11 127.0.0.1 >nul
    goto wait
)

:report
echo.
echo ===== 启动结果 =====
curl -s -m 3 http://127.0.0.1:8085/health 2>nul | findstr /c:"ok" >nul && echo [OK] 8085 35B治疗版 在线 (256K) || echo [FAIL] 未起, 查 D:\llama\server-qwen36-35b.err.log
ping -n 9 127.0.0.1 >nul
exit /b 0
