VERONICA AI - new server install
================================
1. Copy this whole folder to the server as  C:\VeronicaAI
2. Copy your .env file from the old PC (C:\reportbot\.env) into C:\VeronicaAI
   - pen drive only. Never e-mail, WhatsApp or paste it in chat.
3. Double-click INSTALL_ON_SERVER.bat -> click Yes (admin).
   If it installs Python, run it once more after it finishes.
4. Done screen shows the address for office PCs.

Not inside this package (by design):
- .env (keys, passwords)            -> you copy it
- logs, output, old chats          -> stay on old PC
- voice models (models, setup)     -> copy those two folders too if you want the free voice
Database: .env decides. If MySQL + Oracle sync stay on the old PC, change the host in
DATA_DB_URL / BOT_DB_URL from 127.0.0.1 to the old PC's IP, and allow the server's IP
in MySQL on the old PC.
