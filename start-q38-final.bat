@echo off
chcp 65001 >nul
title Qwen3.8-27B Q3-LynnStyle + DFlash2 - stable
cd /d E:\working\llama-cpp\llama

set MODEL=E:\working\models-E\Merkyor\Qwen3.8-27B-EfficientThink-Q3-LynnStyle\Qwen3.8-27B-EfficientThink-SimPO-Q3-LynnStyle.gguf
set MMPROJ=E:\working\gguf-sidecars\qwen38-27b\mmproj-Qwen3.8-27B-Q4_K_M.gguf
set DRAFT=E:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf

echo ==================================================
echo  Qwen3.8-27B Q3-LynnStyle + DFlash2 speculative
echo  Ctx 262144   KV cache: q4_0   FA: on   np: 1
echo  API: http://127.0.0.1:8080/v1
echo  WebUI: http://127.0.0.1:8080
echo ==================================================

llama-server.exe -m "%MODEL%" --mmproj "%MMPROJ%" --model-draft "%DRAFT%" --spec-type draft-dflash --spec-draft-n-max 4 -ngl 99 -ngld 99 -c 262144 -ctk q4_0 -ctv q4_0 -fa on -np 1 --jinja --host 127.0.0.1 --port 8080

pause
