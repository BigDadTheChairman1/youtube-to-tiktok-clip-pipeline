@echo off
rem Runs one channel clip batch and appends everything to channel_log.txt.
rem Used by the Windows scheduled task; safe to double-click manually too.
cd /d %~dp0
python channel_pipeline.py make >> channel_log.txt 2>&1
