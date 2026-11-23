@echo off
rem Opens Bird Photo Editor's log folder and the log file in Notepad.
set "LOGDIR=%LOCALAPPDATA%\BirdPhotoEditor\logs"
if not exist "%LOGDIR%" (
  echo The log folder was not found: %LOGDIR%
  pause
  exit /b 1
)
start "" explorer "%LOGDIR%"
if exist "%LOGDIR%\bird-photo-editor.log" start "" notepad "%LOGDIR%\bird-photo-editor.log"
