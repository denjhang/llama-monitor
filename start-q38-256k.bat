@echo off
title Qwen3.8-27B Q3 + DFlash2 - llama.cpp
cd /d E:\working\llama-cpp\llama

set MODEL=E:\working\models-E\Merkyor\Qwen3.8-27B-EfficientThink-Q3-LynnStyle\Qwen3.8-27B-EfficientThink-SimPO-Q3-LynnStyle.gguf
set DRAFT=E:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf

echo ==================================================
echo  Model  : Qwen3.8-27B EfficientThink Q3-LynnStyle
echo  Draft  : DFlash2 Q8_0  (spec-type draft-dflash)
echo  Ctx    : 262144 (256K)   KV cache: q8_0
echo  API    : http://127.0.0.1:8080/v1   (OpenAI compat)
echo  WebUI  : http://127.0.0.1:8080  (live tok/s monitor)
echo ==================================================
echo  If OOM: lower -c 262144 to 131072 / 65536 first,
echo  then change -ctk/-ctv q8_0 to q4_0
echo ==================================================

llama-server.exe -m "%MODEL%" --model-draft "%DRAFT%" --spec-type draft-dflash --spec-draft-n-max 4 -ngl 99 -ngld 99 -c 262144 -ctk q8_0 -ctv q8_0 --jinja --verbose --host 127.0.0.1 --port 8080

pause
