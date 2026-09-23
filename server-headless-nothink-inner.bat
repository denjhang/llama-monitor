@echo off
cd /d E:\working\llama-cpp\llama-b11139
set MODEL=E:\working\models-E\Merkyor\Qwen3.8-27B-EfficientThink-Q3-LynnStyle\Qwen3.8-27B-EfficientThink-SimPO-Q3-LynnStyle.gguf
set MMPROJ=E:\working\gguf-sidecars\qwen38-27b\mmproj-Qwen3.8-27B-Q4_K_M.gguf
set DRAFT=E:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf
E:\working\llama-cpp\llama-b11139\llama-server.exe -m "%MODEL%" --mmproj "%MMPROJ%" --model-draft "%DRAFT%" --spec-type draft-dflash --spec-draft-n-max 4 -ngl 99 -ngld 99 -c 262144 -ctk q4_0 -ctv q4_0 -fa on -np 1 --jinja --reasoning-budget 0 --host 127.0.0.1 --port 8080 >> llama-server.log 2>&1
