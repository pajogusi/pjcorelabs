#!/usr/bin/env python3
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from werkzeug.security import generate_password_hash

BASE = Path(__file__).resolve().parent
PASS = 0
FAIL = 0


def teste(nome, condicao, detalhe=""):
    global PASS, FAIL
    if condicao:
        PASS += 1
        print(f"✅ PASS  {nome}")
    else:
        FAIL += 1
        print(f"❌ FAIL  {nome}")
        if detalhe:
            print(f"        {detalhe}")


with tempfile.TemporaryDirectory(prefix="blessed-multiuser-") as tmp:
    root = Path(tmp)

    shutil.copy2(BASE / "app.py", root / "app.py")
    shutil.copytree(BASE / "templates", root / "templates")
    (root / "static").mkdir()

    db = root / "blessed.db"

    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE clientes (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT,
            data_nascimento TEXT,
            alerta_inatividade_visto_em TEXT,
            atualizado_em TEXT
        );

        CREATE TABLE telefones (
            id INTEGER PRIMARY KEY,
            cliente_id INTEGER NOT NULL,
            numero TEXT NOT NULL,
            numero_normalizado TEXT NOT NULL,
            atual INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE marcacoes (
            id INTEGER PRIMARY KEY,
            cliente_id INTEGER NOT NULL,
            inicio TEXT NOT NULL,
            duracao_minutos INTEGER NOT NULL,
            servico TEXT NOT NULL DEFAULT '',
            observacoes TEXT,
            estado TEXT NOT NULL DEFAULT 'marcada',
            atualizado_em TEXT
        );
    """)
    con.commit()
    con.close()

    spec = importlib.util.spec_from_file_location(
        "multiuser_app",
        root / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["multiuser_app"] = module
    spec.loader.exec_module(module)

    module.app.config.update(
        TESTING=True,
        SECRET_KEY="test"
    )

    # Nunca enviar SMS reais durante estes testes.
    module.enviar_sms_smsgate = lambda *_args, **_kwargs: True

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    con.executemany(
        """
        INSERT INTO utilizadores
        (nome, username, password_hash, papel)
        VALUES (?, ?, ?, ?)
        """,
        [
            (
                "Bruno",
                "bruno",
                generate_password_hash("bruno-test"),
                "gestor"
            ),
            (
                "Barbeiro Um",
                "um",
                generate_password_hash("um-test"),
                "barbeiro"
            ),
            (
                "Barbeiro Dois",
                "dois",
                generate_password_hash("dois-test"),
                "barbeiro"
            ),
        ],
    )

    con.commit()

    ids = {
        r["username"]: r["id"]
        for r in con.execute(
            "SELECT id, username FROM utilizadores"
        )
    }

    con.close()

    client = module.app.test_client()

    print()
    print("================================================")
    print("     BLESSED MULTIUSER — TESTES AUTOMÁTICOS")
    print("================================================")
    print("BD de teste:", db)
    print()

    # --------------------------------------------------
    # 1. AUTENTICAÇÃO
    # --------------------------------------------------

    r = client.get("/semana")

    teste(
        "Agenda exige autenticação",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    r = client.post(
        "/login",
        data={
            "username": "inexistente",
            "password": "errada"
        }
    )

    teste(
        "Login inválido é rejeitado",
        r.status_code == 401,
        f"HTTP {r.status_code}"
    )

    r = client.post(
        "/login",
        data={
            "username": "um",
            "password": "um-test"
        }
    )

    teste(
        "Barbeiro consegue autenticar",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    # --------------------------------------------------
    # 2. SEPARAÇÃO DAS AGENDAS
    # --------------------------------------------------

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "Cliente A",
            "telefone": "+351910000001",
            "inicio": "2030-01-02T10:00",
            "duracao": "30",
            "barbeiro_id": ids["dois"]
        }
    )

    teste(
        "Barbeiro consegue criar marcação",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    row = con.execute("""
        SELECT id, barbeiro_id, estado
        FROM marcacoes
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    marcacao_id = row["id"]

    teste(
        "Marcação fica na própria agenda do barbeiro",
        row["barbeiro_id"] == ids["um"],
        f'esperado={ids["um"]} obtido={row["barbeiro_id"]}'
    )

    con.close()

    # --------------------------------------------------
    # 3. BARBEIRO NÃO ALTERA AGENDA DE OUTRO
    # --------------------------------------------------

    client.get("/logout")

    client.post(
        "/login",
        data={
            "username": "dois",
            "password": "dois-test"
        }
    )

    r = client.post(
        f"/marcacoes/{marcacao_id}/estado",
        data={"estado": "cancelada"}
    )

    teste(
        "Barbeiro não altera marcação de outro",
        r.status_code == 403,
        f"HTTP {r.status_code}"
    )

    con = sqlite3.connect(db)

    estado = con.execute(
        "SELECT estado FROM marcacoes WHERE id = ?",
        (marcacao_id,)
    ).fetchone()[0]

    con.close()

    teste(
        "Tentativa proibida não altera a BD",
        estado == "marcada",
        f"estado={estado}"
    )

    # --------------------------------------------------
    # 4. PERMISSÕES DO GESTOR
    # --------------------------------------------------

    client.get("/logout")

    client.post(
        "/login",
        data={
            "username": "bruno",
            "password": "bruno-test"
        }
    )

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "Cliente B",
            "telefone": "+351910000002",
            "inicio": "2030-01-02T11:00",
            "duracao": "30",
            "barbeiro_id": ids["dois"]
        }
    )

    teste(
        "Gestor cria marcação para outro profissional",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    row = con.execute("""
        SELECT id, barbeiro_id
        FROM marcacoes
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    gestor_marcacao_id = row["id"]

    teste(
        "Marcação do gestor fica na agenda escolhida",
        row["barbeiro_id"] == ids["dois"],
        f'esperado={ids["dois"]} obtido={row["barbeiro_id"]}'
    )

    con.close()

    r = client.post(
        f"/marcacoes/{gestor_marcacao_id}/estado",
        data={"estado": "cancelada"}
    )

    teste(
        "Gestor consegue alterar marcação de profissional",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    # --------------------------------------------------
    # 5. LOGOUT
    # --------------------------------------------------

    client.get("/logout")

    r = client.get("/semana")

    teste(
        "Logout volta a proteger a agenda",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    print()
    print("================================================")
    print(f"RESULTADO: {PASS} PASS | {FAIL} FAIL")
    print("================================================")

    if FAIL:
        raise SystemExit(1)
