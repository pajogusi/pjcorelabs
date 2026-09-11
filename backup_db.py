import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("/home/paulo/Blessed")
DB = BASE / "blessed.db"
DESTINO = BASE / "backups"
DESTINO.mkdir(exist_ok=True)

agora = datetime.now()
ficheiro = DESTINO / f"blessed-{agora:%Y-%m-%d_%H-%M-%S}.db"

origem = sqlite3.connect(DB)
destino = sqlite3.connect(ficheiro)

try:
    origem.backup(destino)
finally:
    destino.close()
    origem.close()

verificacao = sqlite3.connect(ficheiro)
resultado = verificacao.execute("PRAGMA integrity_check").fetchone()[0]
verificacao.close()

if resultado != "ok":
    ficheiro.unlink(missing_ok=True)
    raise RuntimeError(f"Backup inválido: {resultado}")

limite = agora - timedelta(days=30)

for antigo in DESTINO.glob("blessed-*.db"):
    if datetime.fromtimestamp(antigo.stat().st_mtime) < limite:
        antigo.unlink()

print(f"BACKUP OK: {ficheiro}")
