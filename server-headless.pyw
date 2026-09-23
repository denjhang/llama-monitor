# -*- coding: utf-8 -*-
"""llama-server 无头载入器：pythonw 运行，全程无窗口，独立进程组，杀监控/关任何窗口都不影响"""
import os, subprocess, sys

BIN   = r"E:\working\llama-cpp\llama-b11139\llama-server.exe"
WORK  = r"E:\working\llama-cpp\llama-b11139"
MODEL = r"E:\working\models-E\Merkyor\Qwen3.8-27B-EfficientThink-Q3-LynnStyle\Qwen3.8-27B-EfficientThink-SimPO-Q3-LynnStyle.gguf"
MMPROJ= r"E:\working\gguf-sidecars\qwen38-27b\mmproj-Qwen3.8-27B-Q4_K_M.gguf"
DRAFT = r"E:\working\gguf-sidecars\qwen38-27b\dflash2-qwen38-27b-Q8_0.gguf"

args = [BIN, "-m", MODEL, "--mmproj", MMPROJ, "--model-draft", DRAFT,
        "--spec-type", "draft-dflash", "--spec-draft-n-max", "4",
        "-ngl", "99", "-ngld", "99", "-c", "262144",
        "-ctk", "q4_0", "-ctv", "q4_0", "-fa", "on", "-np", "1", "--jinja",
        "--host", "127.0.0.1", "--port", "8082"]
mode = "nothink" if len(sys.argv) > 1 and sys.argv[1] == "nothink" else "think"
if mode == "nothink":
    args += ["--reasoning-budget", "0"]
open(os.path.join(WORK, "server-mode.txt"), "w").write(mode)

log = open(os.path.join(WORK, "llama-server.log"), "ab")
subprocess.Popen(args, cwd=WORK, stdout=log, stderr=log,
                 creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
