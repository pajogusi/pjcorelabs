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
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
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
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
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
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
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
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
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
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
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
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
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
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
    )

    # --------------------------------------------------
    # 5. LOGOUT
    # --------------------------------------------------

    client.get("/logout")

    r = client.get("/semana")

    teste(
        "Logout volta a proteger a agenda",
        r.status_code in (302, 303),
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
    )


    # --------------------------------------------------
    # 6. ISOLAMENTO DE CONFLITOS ENTRE AGENDAS
    # --------------------------------------------------

    con = sqlite3.connect(module.DB)
    con.row_factory = sqlite3.Row

    utilizadores = con.execute("""
        SELECT id, username
        FROM utilizadores
        WHERE username IN ('um', 'dois')
    """).fetchall()

    ids_conflito = {u["username"]: u["id"] for u in utilizadores}
    con.close()

    client.get("/logout")
    client.post("/login", data={
        "username": "um",
        "password": "um-test"
    })

    inicio_conflito = "2030-06-10T10:00"

    r1 = client.post("/marcacoes/nova", data={
        "nome": "Cliente Agenda Um",
        "telefone": "07111111001",
        "inicio": inicio_conflito,
        "duracao": "30",
        "barbeiro_id": ids_conflito["um"],
    })

    client.get("/logout")
    client.post("/login", data={
        "username": "dois",
        "password": "dois-test"
    })

    r2 = client.post("/marcacoes/nova", data={
        "nome": "Cliente Agenda Dois",
        "telefone": "07111111002",
        "inicio": inicio_conflito,
        "duracao": "30",
        "barbeiro_id": ids_conflito["dois"],
    })

    teste(
        "Dois barbeiros podem ter marcações simultâneas",
        r1.status_code in (302, 303) and r2.status_code in (302, 303),
        f"HTTP agenda 1={r1.status_code}, agenda 2={r2.status_code}"
    )

    con = sqlite3.connect(module.DB)
    con.row_factory = sqlite3.Row

    marcacao_um = con.execute("""
        SELECT id
        FROM marcacoes
        WHERE barbeiro_id = ?
          AND inicio = ?
        ORDER BY id DESC
        LIMIT 1
    """, (
        ids_conflito["um"],
        inicio_conflito
    )).fetchone()

    con.close()

    client.get("/logout")
    client.post("/login", data={
        "username": "um",
        "password": "um-test"
    })

    r = client.post(
        f"/marcacoes/{marcacao_um['id']}/duracao",
        data={"duracao": "45"}
    )

    teste(
        "Alterar duração ignora marcações de outro barbeiro",
        r.status_code == 200,
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:200]}"
    )


    # --------------------------------------------------
    # 7. ISOLAMENTO DE CLIENTES ENTRE BARBEIROS
    # --------------------------------------------------

    client.get("/logout")

    # Criar clientes diretamente na BD para testar apenas permissões.
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    con.execute(
        "INSERT INTO clientes (nome, barbeiro_id) VALUES (?, ?)",
        ("Cliente Privado Um", ids["um"])
    )
    cliente_um_id = con.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    con.execute(
        "INSERT INTO clientes (nome, barbeiro_id) VALUES (?, ?)",
        ("Cliente Privado Dois", ids["dois"])
    )
    cliente_dois_id = con.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    con.execute(
        "INSERT INTO telefones (cliente_id, numero, numero_normalizado, atual) VALUES (?, ?, ?, 1)",
        (cliente_um_id, "07000000001", "07000000001")
    )
    con.execute(
        "INSERT INTO telefones (cliente_id, numero, numero_normalizado, atual) VALUES (?, ?, ?, 1)",
        (cliente_dois_id, "07000000002", "07000000002")
    )

    con.commit()
    con.close()

    # Barbeiro Um entra.
    client.post(
        "/login",
        data={
            "username": "um",
            "password": "um-test"
        }
    )

    # Deve conseguir abrir o seu próprio cliente.
    r = client.get(f"/clientes/{cliente_um_id}")

    teste(
        "Barbeiro consegue consultar o próprio cliente",
        r.status_code == 200,
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
    )

    # Não pode consultar cliente pertencente ao Barbeiro Dois.
    r = client.get(f"/clientes/{cliente_dois_id}")

    teste(
        "Barbeiro não consulta cliente de outro barbeiro",
        r.status_code in (403, 404),
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
    )

    client.get("/logout")

    # Bruno / gestor deve conseguir consultar ambos.
    client.post(
        "/login",
        data={
            "username": "bruno",
            "password": "bruno-test"
        }
    )

    r1 = client.get(f"/clientes/{cliente_um_id}")
    r2 = client.get(f"/clientes/{cliente_dois_id}")

    teste(
        "Gestor consegue consultar clientes de todos os barbeiros",
        r1.status_code == 200 and r2.status_code == 200,
        f"Cliente Um HTTP {r1.status_code} | Cliente Dois HTTP {r2.status_code}"
    )

    client.get("/logout")


    # --------------------------------------------------
    # 8. CLIENTES E MARCAÇÕES ENTRE BARBEIROS
    # --------------------------------------------------

    client.get("/logout")

    # Obter os clientes criados no teste anterior.
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    cliente_um = con.execute(
        "SELECT id FROM clientes WHERE nome = ? ORDER BY id DESC LIMIT 1",
        ("Cliente Privado Um",)
    ).fetchone()

    cliente_dois = con.execute(
        "SELECT id FROM clientes WHERE nome = ? ORDER BY id DESC LIMIT 1",
        ("Cliente Privado Dois",)
    ).fetchone()

    con.close()

    # --------------------------------------------------
    # Barbeiro Um NÃO pode marcar cliente do Barbeiro Dois
    # --------------------------------------------------

    client.post(
        "/login",
        data={
            "username": "um",
            "password": "um-test"
        }
    )

    inicio_teste = "2030-07-10T14:00"

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "Cliente Privado Dois",
            "telefone": "07000000002",
            "barbeiro_id": str(ids["um"]),
            "inicio": inicio_teste,
            "duracao": "30",
            "servico": "Teste isolamento cliente"
        }
    )

    con = sqlite3.connect(db)
    tentativa_cliente_alheio = con.execute(
        """
        SELECT COUNT(*)
        FROM marcacoes
        WHERE cliente_id = ?
          AND barbeiro_id = ?
          AND inicio = ?
        """,
        (
            cliente_dois["id"],
            ids["um"],
            inicio_teste
        )
    ).fetchone()[0]
    con.close()

    teste(
        "Barbeiro não marca cliente pertencente a outro barbeiro",
        tentativa_cliente_alheio == 0,
        f"HTTP {r.status_code} | marcações criadas {tentativa_cliente_alheio}"
    )

    # --------------------------------------------------
    # Barbeiro Um NÃO pode marcar na agenda do Barbeiro Dois
    # --------------------------------------------------

    inicio_teste_2 = "2030-07-10T15:00"

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "Cliente Privado Um",
            "telefone": "07000000001",
            "barbeiro_id": str(ids["dois"]),
            "inicio": inicio_teste_2,
            "duracao": "30",
            "servico": "Teste agenda alheia"
        }
    )

    con = sqlite3.connect(db)
    marcacao_agenda_dois = con.execute(
        """
        SELECT COUNT(*)
        FROM marcacoes
        WHERE cliente_id = ?
          AND barbeiro_id = ?
          AND inicio = ?
        """,
        (
            cliente_um["id"],
            ids["dois"],
            inicio_teste_2
        )
    ).fetchone()[0]
    con.close()

    teste(
        "Barbeiro não cria marcação na agenda de outro barbeiro",
        marcacao_agenda_dois == 0,
        f"HTTP {r.status_code} | marcações criadas {marcacao_agenda_dois}"
    )

    client.get("/logout")

    # --------------------------------------------------
    # Bruno / gestor PODE colocar cliente do B2 no B1
    # --------------------------------------------------

    client.post(
        "/login",
        data={
            "username": "bruno",
            "password": "bruno-test"
        }
    )

    inicio_gestor = "2030-07-10T16:00"

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "Cliente Privado Dois",
            "telefone": "07000000002",
            "barbeiro_id": str(ids["um"]),
            "inicio": inicio_gestor,
            "duracao": "30",
            "servico": "Teste gestor entre agendas"
        }
    )

    con = sqlite3.connect(db)
    marcacao_gestor = con.execute(
        """
        SELECT id, cliente_id, barbeiro_id
        FROM marcacoes
        WHERE cliente_id = ?
          AND barbeiro_id = ?
          AND inicio = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            cliente_dois["id"],
            ids["um"],
            inicio_gestor
        )
    ).fetchone()
    con.close()

    teste(
        "Gestor pode marcar cliente de um barbeiro noutro barbeiro",
        marcacao_gestor is not None,
        f"HTTP {r.status_code} | resposta {r.get_data(as_text=True)[:500]}"
    )

    client.get("/logout")

    print()
    print("================================================")
    print(f"RESULTADO: {PASS} PASS | {FAIL} FAIL")
    print("================================================")

    if FAIL:
        raise SystemExit(1)
