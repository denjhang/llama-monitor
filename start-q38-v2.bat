@echo off
chcp 65001 >nul
title Qwen3.8-27B Q3 + DFlash2 v2 - merged best config
cd /d E:\working\llama-cpp\llama

set MODEL=E:\working\models-E\Merkyor\Qwen3.8-27B-EfficientThink-Q3-LynnStyle\Qwen3.8-27B-EfficientThink-SimPO-Q3-LynnStyle.gguf
set MMPROJ=E:\working\models-E\Merkyor\Qwen3.8-27B-EfficientThink-Q3-LynnStyle\mmproj-Qwen3.8-27B-Q8_0.gguf
set DRAFT=E:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf
set TEMPLATE=E:\working\llama-cpp\chat_template-v22.5.jinja

echo =================================================================
echo  Qwen3.8-27B Q3-LynnStyle + DFlash2+ngram dual spec + v22.5 template
echo  Ctx 262144 (KV q4_0, cram 16GB RAM overflow) + reasoning medium
echo  Sampling baked in: temp 1.0 / top_p 0.95 / top_k 20 / min_p 0
echo  API: http://127.0.0.1:8080/v1    WebUI: http://127.0.0.1:8080
echo =================================================================
echo  If OOM: -c 262144 -> 131072, or drop --cache-ram
echo  If treatment model misbehaves with v22.5, remove
echo  --chat-template-file line (falls back to embedded template)
echo =================================================================

llama-server.exe -m "%MODEL%" --mmproj "%MMPROJ%" --no-mmproj-offload --image-min-tokens 1024 --model-draft "%DRAFT%" --spec-type draft-dflash --spec-draft-n-max 2 --spec-draft-p-min 0.6 -ngl all -ngld all -np 1 --parallel 1 -c 262144 --cache-ram 16384 -ctk q4_0 -ctv q4_0 -fa on --fit off -b 4096 -ub 2048 --cache-reuse 256 --prio 2 --jinja --chat-template-file "%TEMPLATE%" --reasoning-effort medium --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 --repeat-penalty 1.0 --verbose --host 0.0.0.0 --port 8080

pause
