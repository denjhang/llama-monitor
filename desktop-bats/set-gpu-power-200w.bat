@echo off
REM ============================================================
REM  Set GPU power limit to 200W on all 5 cards  (2026-11-06)
REM
REM  WHY THIS IS REQUIRED
REM    The power supply is 2000W total. At the default 320W
REM    limit, a 4-way real split peaks around 2050W for the
REM    whole machine (5x320 GPU + 300 dual Xeon + 150 other),
REM    which exceeds the PSU rating - the transient spike trips
REM    protection and the machine hard-powers-off.
REM    Symptom: Kernel-Power 41, BugcheckCode=0, no minidump.
REM    At 200W the whole machine peaks around 1216W (40% head).
REM    Measured decode is unaffected: 138 t/s, and the five
REM    GPUs together only draw about 766W (decode is bound by
REM    VRAM bandwidth, not SM compute).
REM    Detail: D:\llama-monitor\docs\11-06-*.md
REM
REM  nvidia-smi -pl does NOT survive a reboot, so run this once
REM  after every boot, BEFORE starting the engine.
REM  A boot task also runs it automatically:
REM    task name "GPU-PowerLimit-200W"  (AtStartup + 30s, SYSTEM)
REM
REM  LOOK FOR THIS LINE IN THE OUTPUT:
REM    [OK] all GPUs capped at 200W
REM  The script self-elevates, so double-click is enough.
REM ============================================================
title Set GPU power limit 200W

net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

echo [1/2] Applying 200W power limit to every GPU...
nvidia-smi -pl 200 >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo [2/2] Verifying...
set /a over=0
for /f "tokens=*" %%p in ('nvidia-smi --query-gpu^=power.limit --format^=csv^,noheader^,nounits') do (
    for /f "tokens=1 delims=." %%v in ("%%p") do (
        if %%v GTR 200 set /a over+=1
    )
)

echo.
echo ===== Result =====
if %over% EQU 0 (
    echo [OK] all GPUs capped at 200W
) else (
    echo [FAIL] %over% GPU^(s^) still above 200W
)
echo.

echo ===== Current limits =====
nvidia-smi --query-gpu=index,name,power.limit,power.default_limit --format=csv
echo.

echo Order: run this first, then the engine launcher.
echo Note : nvidia-smi -pl is lost on reboot and must be reapplied.
echo        Boot task "GPU-PowerLimit-200W" does it automatically.
ping -n 14 127.0.0.1 >nul
exit /b 0
