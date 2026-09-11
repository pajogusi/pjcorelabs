#!/bin/bash
set -e

BASE="/home/paulo/Blessed"
BACKUPS="$BASE/backups"
PYTHON="$BASE/.venv/bin/python"

echo
echo "======================================"
echo "     RECUPERACAO DA BASE BLESSED"
echo "======================================"
echo

mapfile -t ficheiros < <(find "$BACKUPS" -maxdepth 1 -type f -name 'blessed-*.db' -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)

if [ ${#ficheiros[@]} -eq 0 ]; then
    echo "ERRO: não existem backups."
    exit 1
fi

echo "Backups disponíveis:"
echo

for i in "${!ficheiros[@]}"; do
    printf "%2d) %s\n" "$((i+1))" "$(basename "${ficheiros[$i]}")"
done

echo
read -rp "Escolhe o número do backup a restaurar: " escolha

if ! [[ "$escolha" =~ ^[0-9]+$ ]] || \
   [ "$escolha" -lt 1 ] || \
   [ "$escolha" -gt "${#ficheiros[@]}" ]; then
    echo "Escolha inválida."
    exit 1
fi

BACKUP="${ficheiros[$((escolha-1))]}"

echo
echo "Selecionado: $(basename "$BACKUP")"
echo

# Verificar backup ANTES de tocar na base atual
RESULTADO=$("$PYTHON" - "$BACKUP" <<'PY'
import sqlite3
import sys

db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
try:
    print(con.execute("PRAGMA integrity_check").fetchone()[0])
finally:
    con.close()
PY
)

if [ "$RESULTADO" != "ok" ]; then
    echo "ERRO: o backup selecionado não passou a verificação."
    echo "Resultado: $RESULTADO"
    exit 1
fi

echo "Integridade do backup: OK"
echo
read -rp "CONFIRMAR RESTAURO? Escreve SIM: " confirma

if [ "$confirma" != "SIM" ]; then
    echo "Restauro cancelado."
    exit 0
fi

echo
echo "A parar Blessed..."
sudo systemctl stop blessed.service

# Backup de emergência da base que vamos substituir
EMERGENCIA="$BACKUPS/pre-restauro-$(date +%Y-%m-%d_%H-%M-%S).db"

"$PYTHON" - "$BASE/blessed.db" "$EMERGENCIA" <<'PY'
import sqlite3
import sys

origem = sqlite3.connect(sys.argv[1])
destino = sqlite3.connect(sys.argv[2])

try:
    origem.backup(destino)
finally:
    destino.close()
    origem.close()
PY

echo "Backup de emergência:"
echo "$EMERGENCIA"

# Restaurar através do SQLite
"$PYTHON" - "$BACKUP" "$BASE/blessed.db" <<'PY'
import sqlite3
import sys

origem = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
destino = sqlite3.connect(sys.argv[2])

try:
    origem.backup(destino)
finally:
    destino.close()
    origem.close()
PY

echo "Base restaurada."

sudo systemctl start blessed.service
sleep 1

echo
echo "======================================"
echo "RESTAURO TERMINADO"
echo "SERVICO: $(systemctl is-active blessed.service)"
echo "BACKUP USADO: $(basename "$BACKUP")"
echo "EMERGENCIA: $(basename "$EMERGENCIA")"
echo "======================================"
