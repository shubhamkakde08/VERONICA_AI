# Offline backup voice (optional)
The model files are too big for GitHub, so they are not in this repo. VERONICA works without them (Gemini voice only).
To add the free offline backup voice, download these two files from
https://github.com/thewh1teagle/kokoro-onnx/releases (tag "model-files-v1.0") into this folder:
- kokoro-v1.0.int8.onnx
- voices-v1.0.bin
Then run:  .venv\Scripts\python.exe -m pip install kokoro-onnx soundfile
