#!/usr/bin/env python3
"""Cria ou repõe um utilizador da versão multiutilizador sem expor palavras-passe."""
import argparse
import getpass
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

parser = argparse.ArgumentParser()
parser.add_argument("nome")
parser.add_argument("username")
parser.add_argument("--papel", choices=("gestor", "barbeiro"), default="barbeiro")
parser.add_argument("--marcar-outros", action="store_true", help="Permite consultar e criar marcações para outros barbeiros")
args = parser.parse_args()

password = getpass.getpass("Palavra-passe: ")
confirmacao = getpass.getpass("Repetir palavra-passe: ")
if not password or password != confirmacao:
    raise SystemExit("As palavras-passe não coincidem.")

db = Path(__file__).with_name("blessed.db")
con = sqlite3.connect(db)
con.execute("""
    INSERT INTO utilizadores (nome, username, password_hash, papel, ativo, pode_consultar_agendas, pode_marcar_outros)
    VALUES (?, ?, ?, ?, 1, ?, ?)
    ON CONFLICT(username) DO UPDATE SET
        nome = excluded.nome,
        password_hash = excluded.password_hash,
        papel = excluded.papel,
        ativo = 1,
        pode_consultar_agendas = excluded.pode_consultar_agendas,
        pode_marcar_outros = excluded.pode_marcar_outros,
        atualizado_em = CURRENT_TIMESTAMP
""", (args.nome, args.username, generate_password_hash(password), args.papel, int(args.marcar_outros), int(args.marcar_outros)))
con.commit()
con.close()
print(f"Utilizador '{args.username}' preparado.")
