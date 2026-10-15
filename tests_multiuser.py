#!/usr/bin/env python3
import importlib.util
import os
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


def login(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
    )


def abrir_agenda(client, barbeiro_id):
    # Reproduz o estado criado quando o utilizador abre uma agenda individual.
    with client.session_transaction() as session:
        session["agenda_aberta_id"] = int(barbeiro_id)


def criar_marcacao(client, barbeiro_id, nome, telefone, inicio, **extra):
    abrir_agenda(client, barbeiro_id)
    dados = {
        "nome": nome,
        "telefone": telefone,
        "inicio": inicio,
        "duracao": "30",
    }
    dados.update(extra)
    return client.post("/marcacoes/nova", data=dados)


with tempfile.TemporaryDirectory(prefix="blessed-multiuser-") as tmp:
    root = Path(tmp)
    db = root / "blessed.db"

    shutil.copy2(BASE / "app.py", root / "app.py")
    shutil.copytree(BASE / "templates", root / "templates")
    (root / "static").mkdir()

    # A aplicação e os testes usam exclusivamente esta BD temporária.
    os.environ["BLESSED_DB"] = str(db)
    os.environ["BLESSED_DISABLE_SMS"] = "1"

    spec = importlib.util.spec_from_file_location(
        "multiuser_app",
        root / "app.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["multiuser_app"] = module
    spec.loader.exec_module(module)

    module.app.config.update(TESTING=True, SECRET_KEY="test")

    # Defesa adicional: nunca entregar SMS reais durante estes testes.
    module.enviar_sms_smsgate = lambda *_args, **_kwargs: True
    module.enviar_sms_smsto = lambda *_args, **_kwargs: True

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executemany(
        """
        INSERT INTO utilizadores
        (nome, username, password_hash, papel, ativo, e_admin,
         pode_consultar_agendas, pode_marcar_outros, sms_autorizado)
        VALUES (?, ?, ?, ?, 1, 0, 1, 1, 0)
        """,
        [
            ("Bruno", "bruno", generate_password_hash("bruno-test"), "gestor"),
            ("Barbeiro Um", "um", generate_password_hash("um-test"), "barbeiro"),
            ("Barbeiro Dois", "dois", generate_password_hash("dois-test"), "barbeiro"),
        ],
    )
    con.commit()
    ids = {
        r["username"]: r["id"]
        for r in con.execute("SELECT id, username FROM utilizadores")
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
        f"HTTP {r.status_code}",
    )

    r = login(client, "inexistente", "errada")
    teste(
        "Login inválido é rejeitado",
        r.status_code == 401,
        f"HTTP {r.status_code}",
    )

    r = login(client, "um", "um-test")
    teste(
        "Barbeiro consegue autenticar",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}",
    )

    # --------------------------------------------------
    # 2. A AGENDA ABERTA DEFINE O PROFISSIONAL
    # --------------------------------------------------
    r = criar_marcacao(
        client,
        ids["dois"],
        "Cliente A",
        "+351910000001",
        "2030-01-02T10:00",
        # Campo adulterado de propósito: deve ser ignorado.
        barbeiro_id=str(ids["um"]),
    )
    teste(
        "Barbeiro cria marcação na agenda individual aberta",
        r.status_code in (302, 303),
        f"HTTP {r.status_code} | {r.get_data(as_text=True)[:300]}",
    )

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute(
        """
        SELECT id, barbeiro_id, criado_por_id, estado
        FROM marcacoes
        WHERE inicio = '2030-01-02T10:00'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    con.close()

    teste("Marcação foi criada", row is not None)
    marcacao_cross_id = row["id"] if row else None
    teste(
        "Agenda aberta prevalece sobre barbeiro_id enviado no formulário",
        bool(row and row["barbeiro_id"] == ids["dois"]),
        f"esperado={ids['dois']} obtido={row['barbeiro_id'] if row else None}",
    )
    teste(
        "Criador da marcação fica registado",
        bool(row and row["criado_por_id"] == ids["um"]),
        f"esperado={ids['um']} obtido={row['criado_por_id'] if row else None}",
    )

    # --------------------------------------------------
    # 3. PERMISSÕES DE ALTERAÇÃO
    # --------------------------------------------------
    client.get("/logout")
    login(client, "dois", "dois-test")
    r = client.post(
        f"/marcacoes/{marcacao_cross_id}/estado",
        data={"estado": "faltou"},
    )
    teste(
        "Barbeiro responsável altera a própria marcação",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}",
    )

    # Criar pelo gestor uma marcação do Barbeiro Dois; Barbeiro Um não é
    # responsável nem criador e não a pode alterar.
    client.get("/logout")
    login(client, "bruno", "bruno-test")
    r = criar_marcacao(
        client,
        ids["dois"],
        "Cliente Protegido",
        "+351910000009",
        "2030-01-02T12:00",
    )
    teste(
        "Gestor cria marcação para qualquer profissional",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}",
    )

    con = sqlite3.connect(db)
    protegida_id = con.execute(
        "SELECT id FROM marcacoes WHERE inicio = '2030-01-02T12:00' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    con.close()

    client.get("/logout")
    login(client, "um", "um-test")
    r = client.post(
        f"/marcacoes/{protegida_id}/estado",
        data={"estado": "cancelada"},
    )
    teste(
        "Barbeiro não altera marcação de outro que não criou",
        r.status_code == 403,
        f"HTTP {r.status_code} | {r.get_data(as_text=True)[:200]}",
    )

    con = sqlite3.connect(db)
    estado = con.execute(
        "SELECT estado FROM marcacoes WHERE id = ?", (protegida_id,)
    ).fetchone()[0]
    con.close()
    teste(
        "Tentativa 403 não altera a BD",
        estado == "marcada",
        f"estado={estado}",
    )

    # Gestor pode alterar a mesma marcação.
    client.get("/logout")
    login(client, "bruno", "bruno-test")
    r = client.post(
        f"/marcacoes/{protegida_id}/estado",
        data={"estado": "cancelada"},
    )
    teste(
        "Gestor altera marcação de profissional",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}",
    )

    # --------------------------------------------------
    # 4. CONFLITOS ISOLADOS POR AGENDA
    # --------------------------------------------------
    client.get("/logout")
    login(client, "um", "um-test")
    r1 = criar_marcacao(
        client, ids["um"], "Agenda Um", "07111111001", "2030-06-10T10:00"
    )
    r2 = criar_marcacao(
        client, ids["dois"], "Agenda Dois", "07111111002", "2030-06-10T10:00"
    )
    teste(
        "Dois profissionais podem ter marcações simultâneas",
        r1.status_code in (302, 303) and r2.status_code in (302, 303),
        f"HTTP agenda1={r1.status_code}, agenda2={r2.status_code}",
    )

    # --------------------------------------------------
    # 5. CLIENTES SÃO PARTILHADOS
    # --------------------------------------------------
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute(
        "INSERT INTO clientes (nome, barbeiro_id) VALUES (?, ?)",
        ("Cliente Partilhado", ids["dois"]),
    )
    cliente_partilhado_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.execute(
        """
        INSERT INTO telefones
        (cliente_id, numero, numero_normalizado, atual)
        VALUES (?, ?, ?, 1)
        """,
        (cliente_partilhado_id, "07000000022", "07000000022"),
    )
    con.commit()
    con.close()

    # Continua autenticado como Barbeiro Um.
    r = client.get(f"/clientes/{cliente_partilhado_id}")
    teste(
        "Barbeiro consulta cliente criado por outro profissional",
        r.status_code == 200,
        f"HTTP {r.status_code}",
    )

    r = criar_marcacao(
        client,
        ids["um"],
        "Cliente Partilhado",
        "07000000022",
        "2030-07-10T14:00",
        cliente_id=str(cliente_partilhado_id),
    )
    teste(
        "Barbeiro marca cliente partilhado na agenda escolhida",
        r.status_code in (302, 303),
        f"HTTP {r.status_code} | {r.get_data(as_text=True)[:300]}",
    )

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    partilhada = con.execute(
        """
        SELECT cliente_id, barbeiro_id, criado_por_id
        FROM marcacoes
        WHERE inicio = '2030-07-10T14:00'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    con.close()
    teste(
        "Marcação reutiliza o mesmo cliente global",
        bool(partilhada and partilhada["cliente_id"] == cliente_partilhado_id),
        f"cliente={partilhada['cliente_id'] if partilhada else None}",
    )
    teste(
        "Cliente partilhado fica na agenda atualmente aberta",
        bool(partilhada and partilhada["barbeiro_id"] == ids["um"]),
        f"barbeiro={partilhada['barbeiro_id'] if partilhada else None}",
    )

    # --------------------------------------------------
    # 6. LOGOUT
    # --------------------------------------------------
    client.get("/logout")
    r = client.get("/semana")
    teste(
        "Logout volta a proteger a agenda",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}",
    )

    print()
    print("================================================")
    print(f"RESULTADO: {PASS} PASS | {FAIL} FAIL")
    print("================================================")

    if FAIL:
        raise SystemExit(1)
