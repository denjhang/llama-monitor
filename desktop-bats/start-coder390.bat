@echo off
REM ============================================================
REM  start-coder390.bat
REM  模型: Qwen3.8-27B-Coder390-EfficientThink (代码专精)
REM  显卡: CUDA2,CUDA3 双卡    端口: 8084
REM  草稿: DFlash2 (z-lab/Qwen3.8-27B-DFlash2-GGUF, 专用配对, 必须同卡!)
REM  实测(ik_llama 38c333c/v36, 32K ctx): 36-52 t/s decode / 40-100 t/s prefill
REM  2026-10-23 穷举: n_max=3略优于4(36-39 vs 32)、KV q4=q8无效、单卡坍塌、graph -42%
REM  速度由草稿接受率驱动: 长会话续写0.85-0.95→45-52, 独立新请求0.65-0.77→32-39
REM  实测负收益: MTP投机(-25%)、跨卡草稿(-50%)、4卡layer split(-70%)、graph split(-42%)
REM  注意: 草稿必须 --device-draft CUDA2（与主模型首卡同卡），跨卡走PCIe会饿死
REM ============================================================
chcp 65001 >nul
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8084 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1

powershell -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'D:\llama-ik\build\bin\llama-server.exe' -ArgumentList '-m','D:\working\models\nerkyor\Qwen3.8-27B-Coder390-EfficientThink-Q3LynnStyle\Qwen3.8-27B-Coder390-EfficientThink-Q3LynnStyle-MTP.gguf','--model-draft','D:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf','--mmproj','D:\working\models\nerkyor\Qwen3.8-27B-Coder390-EfficientThink-Q3LynnStyle\mmproj-Qwen3.8-27B-Q8_0.gguf','--device','CUDA2,CUDA3','--device-draft','CUDA2','-ngl','99','-ngld','99','-c','32768','--parallel','1','-ub','2048','-b','8192','-ctk','q4_0','-ctv','q4_0','-fa','on','--spec-type','dflash:n_max=3','--metrics','--jinja','--reasoning-budget','0','--alias','qwen3.8-27b-coder390','--host','0.0.0.0','--port','8084' -RedirectStandardOutput 'D:\llama\server-coder390-ik.log' -RedirectStandardError 'D:\llama\server-coder390-ik.err.log'"

echo [coder390] loading on CUDA2,3 + DFlash2 draft on CUDA2 - port 8084 ...
powershell -NoProfile -Command "for($i=0;$i -lt 42;$i++){Start-Sleep 10; try{$r=Invoke-RestMethod http://127.0.0.1:8084/health -TimeoutSec 5; if($r.status -eq 'ok'){exit 0}}catch{}}; exit 1"
if errorlevel 1 (echo [ERROR] coder390 failed. See D:\llama\server-coder390.err.log & exit /b 1)
echo [coder390] READY on 8084.
