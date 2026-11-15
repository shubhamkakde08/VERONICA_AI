@echo off
REM Installs VERONICA's free, unlimited, offline BACKUP voice (Kokoro TTS). No internet needed - first put the model files in models\kokoro - see models\kokoro\README.md.
REM Her Gemini voice stays the main voice; Kokoro speaks only when Gemini's daily limit is used up.
cd /d "%~dp0"
echo.
echo  ===== Installing VERONICA's free backup voice (Kokoro, offline) =====
echo.
.venv\Scripts\python.exe -m pip install kokoro-onnx soundfile
if errorlevel 1 (
  echo.
  echo  Package install FAILED - send a screenshot of this window to Claude.
  pause
  exit /b 1
)
echo.
echo Testing the backup voice...
.venv\Scripts\python.exe -c "from app import local_tts, voice; print('Free voice available:', local_tts.available()); open('voice_test_free.mp3','wb').write(voice._kokoro_speak('Hello Boss! This is my backup voice. How can I help you today?','en-IN','audio/mp3')); print('Saved voice_test_free.mp3')"
echo.
echo  DONE. Now double-click RESTART_VERONICA.bat, then Ctrl+F5 in the browser.
echo  (Play voice_test_free.mp3 in this folder to hear the backup voice.)
pause
