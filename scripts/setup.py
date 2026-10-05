"""Generate local settings without installing dependencies or overwriting secrets."""
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if env_file.exists():
    print(".env already exists; left unchanged.")
else:
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("DJANGO_SECRET_KEY=" + secrets.token_urlsafe(64) + "\n")
        f.write("DJANGO_DEBUG=0\nDJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1]\n")
    print("Created .env with an individual secret key.")
for directory in [root / "data", root / "backups"]:
    directory.mkdir(mode=0o700, exist_ok=True)
print("Settings ready. See README.md for startup commands.")
