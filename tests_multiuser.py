#!/usr/bin/env python3
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from werkzeug.security import generate_password_hash

BASE = Path(__file__).resolve().parent

with tempfile.TemporaryDirectory(prefix="blessed-multiuser-") as tmp:
    root = Path(tmp)
    shutil.copy2(BASE / "app.py", root / "app.py")
    shutil.copytree(BASE / "templates", root / "templates")
    (root / "static").mkdir()
    db = root / "blessed.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, email TEXT, data_nascimento TEXT, alerta_inatividade_visto_em TEXT, atualizado_em TEXT);
        CREATE TABLE telefones (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL, numero TEXT NOT NULL, numero_normalizado TEXT NOT NULL, atual INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE marcacoes (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL, inicio TEXT NOT NULL, duracao_minutos INTEGER NOT NULL, servico TEXT NOT NULL DEFAULT '', observacoes TEXT, estado TEXT NOT NULL DEFAULT 'marcada', atualizado_em TEXT);
    """)
    con.commit()
    con.close()

    spec = importlib.util.spec_from_file_location("multiuser_app", root / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["multiuser_app"] = module
    spec.loader.exec_module(module)
    module.app.config.update(TESTING=True, SECRET_KEY="test")
    module.enviar_sms_smsgate = lambda *_: True

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executemany(
        "INSERT INTO utilizadores (nome, username, password_hash, papel) VALUES (?, ?, ?, ?)",
        [
            ("Bruno", "bruno", generate_password_hash("bruno-test"), "gestor"),
            ("Barbeiro Um", "um", generate_password_hash("um-test"), "barbeiro"),
            ("Barbeiro Dois", "dois", generate_password_hash("dois-test"), "barbeiro"),
        ],
    )
    con.commit()
    ids = {r["username"]: r["id"] for r in con.execute("SELECT id, username FROM utilizadores")}
    con.close()

    client = module.app.test_client()
    assert client.get("/semana").status_code == 302
    assert client.post("/login", data={"username": "um", "password": "um-test"}).status_code == 302
    r = client.post("/marcacoes/nova", data={"nome": "Cliente A", "telefone": "+351910000001", "inicio": "2030-01-02T10:00", "duracao": "30", "barbeiro_id": ids["dois"]})
    assert r.status_code == 302
    con = sqlite3.connect(db)
    marcacao = con.execute("SELECT barbeiro_id FROM marcacoes").fetchone()[0]
    assert marcacao == ids["um"]
    marcacao_id = con.execute("SELECT id FROM marcacoes").fetchone()[0]
    con.close()

    client.get("/logout")
    client.post("/login", data={"username": "dois", "password": "dois-test"})
    assert client.post(f"/marcacoes/{marcacao_id}/estado", data={"estado": "cancelada"}).status_code == 403

    client.get("/logout")
    client.post("/login", data={"username": "bruno", "password": "bruno-test"})
    r = client.post("/marcacoes/nova", data={"nome": "Cliente B", "telefone": "+351910000002", "inicio": "2030-01-02T10:00", "duracao": "30", "barbeiro_id": ids["dois"]})
    assert r.status_code == 302
    print("PASS: autenticação, separação de agendas e acesso do gestor")
