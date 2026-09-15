#!/usr/bin/env python3

import hashlib
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Código que está efetivamente a ser testado.
BASE = Path(__file__).resolve().parent

# Produção: usada apenas para confirmar que os testes nunca a alteram.
REAL_DB = Path("/home/paulo/Blessed/blessed.db")

PASS = 0
FAIL = 0


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


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


hash_antes = sha256(REAL_DB)

with tempfile.TemporaryDirectory(prefix="blessed-tests-") as tmp:
    TMP = Path(tmp)

    # Cópia isolada da aplicação necessária para os testes
    shutil.copy2(BASE / "app.py", TMP / "app.py")
    shutil.copy2(REAL_DB, TMP / "blessed.db")
    shutil.copytree(BASE / "templates", TMP / "templates")
    shutil.copytree(BASE / "static", TMP / "static")

    spec = importlib.util.spec_from_file_location("blessed_test_app", TMP / "app.py")
    appmod = importlib.util.module_from_spec(spec)
    sys.modules["blessed_test_app"] = appmod
    spec.loader.exec_module(appmod)

    app = appmod.app
    app.config.update(TESTING=True)

    client = app.test_client()

    def db():
        con = sqlite3.connect(TMP / "blessed.db")
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    print()
    print("==============================================")
    print("     BLESSED — BATERIA AUTOMÁTICA DE TESTES")
    print("==============================================")
    print("BASE REAL:", REAL_DB)
    print("BASE TESTE:", TMP / "blessed.db")
    print()

    # -----------------------------------------------------
    # 1. BASE / INTEGRIDADE
    # -----------------------------------------------------
    con = db()

    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    teste("SQLite integrity_check", integrity == "ok", integrity)

    tabelas = {
        r["name"]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    for tabela in ["clientes", "telefones", "marcacoes", "definicoes"]:
        teste(f"Tabela {tabela} existe", tabela in tabelas)

    col_marcacoes = {
        r["name"] for r in con.execute("PRAGMA table_info(marcacoes)")
    }
    teste("marcacoes.observacoes existe", "observacoes" in col_marcacoes)

    col_clientes = {
        r["name"] for r in con.execute("PRAGMA table_info(clientes)")
    }
    teste(
        "clientes.alerta_inatividade_visto_em existe",
        "alerta_inatividade_visto_em" in col_clientes
    )

    con.close()

    # -----------------------------------------------------
    # 2. ROTAS PRINCIPAIS
    # -----------------------------------------------------
    rotas = [
        "/",
        "/semana",
        "/hoje",
        "/clientes",
        "/clientes?top=10",
        "/clientes?inativos=1",
        "/servicos",
        "/produtos",
        "/definicoes",
    ]

    for rota in rotas:
        r = client.get(rota)
        teste(
            f"GET {rota}",
            r.status_code == 200,
            f"HTTP {r.status_code}"
        )

    # Cliente inexistente
    r = client.get("/clientes/999999")
    teste(
        "Ficha de cliente inexistente devolve 404",
        r.status_code == 404,
        f"HTTP {r.status_code}"
    )

    # -----------------------------------------------------
    # 3. DEFINIÇÕES
    # -----------------------------------------------------
    con = db()
    valor_original = appmod.obter_dias_inatividade(con)
    con.close()

    teste(
        "Dias inatividade inicialmente válidos",
        15 <= valor_original <= 365,
        str(valor_original)
    )

    r = client.post(
        "/definicoes",
        data={"dias_inatividade": "90"},
        follow_redirects=False
    )
    teste(
        "Alterar inatividade para 90 dias",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    con = db()
    valor = appmod.obter_dias_inatividade(con)
    con.close()
    teste("Definição 90 dias persistiu", valor == 90, str(valor))

    # Limite mínimo
    client.post("/definicoes", data={"dias_inatividade": "1"})
    con = db()
    valor = appmod.obter_dias_inatividade(con)
    con.close()
    teste("Limite mínimo aplicado = 15", valor == 15, str(valor))

    # Limite máximo
    client.post("/definicoes", data={"dias_inatividade": "999"})
    con = db()
    valor = appmod.obter_dias_inatividade(con)
    con.close()
    teste("Limite máximo aplicado = 365", valor == 365, str(valor))

    # Repor 60 na cópia de teste
    client.post("/definicoes", data={"dias_inatividade": "60"})

    # -----------------------------------------------------
    # 4. NORMALIZAÇÃO DE TELEFONE
    # -----------------------------------------------------
    teste(
        "Normalização telefone simples",
        appmod.normalizar_telefone(" 912 345 678 ") == "912345678"
    )

    teste(
        "Normalização mantém +",
        appmod.normalizar_telefone("+351 912 345 678") == "+351912345678"
    )

    # -----------------------------------------------------
    # 5. CRIAÇÃO DE CLIENTE + MARCAÇÃO
    # -----------------------------------------------------
    futuro = datetime.now() + timedelta(days=20)
    futuro = futuro.replace(hour=10, minute=0, second=0, microsecond=0)

    inicio1 = futuro.strftime("%Y-%m-%dT%H:%M")
    telefone = "+351 910 000 001"

    con = db()
    clientes_antes = con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    marcacoes_antes = con.execute("SELECT COUNT(*) FROM marcacoes").fetchone()[0]
    con.close()

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "TESTE AUTOMATICO A",
            "telefone": telefone,
            "email": "teste-a@example.invalid",
            "data_nascimento": "1980-01-02",
            "inicio": inicio1,
            "duracao": "30",
            "servico": "Corte",
            "observacoes": "Teste automático",
        },
        follow_redirects=False,
    )

    teste(
        "Criar nova marcação",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    con = db()
    clientes_depois = con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    marcacoes_depois = con.execute("SELECT COUNT(*) FROM marcacoes").fetchone()[0]

    cliente = con.execute("""
        SELECT c.id, c.nome, c.email, t.numero_normalizado
        FROM clientes c
        JOIN telefones t ON t.cliente_id = c.id
        WHERE t.numero_normalizado = ?
        ORDER BY t.id DESC
        LIMIT 1
    """, (appmod.normalizar_telefone(telefone),)).fetchone()

    teste(
        "Cliente novo foi criado exatamente uma vez",
        clientes_depois == clientes_antes + 1,
        f"{clientes_antes} -> {clientes_depois}"
    )

    teste(
        "Marcação nova foi criada exatamente uma vez",
        marcacoes_depois == marcacoes_antes + 1,
        f"{marcacoes_antes} -> {marcacoes_depois}"
    )

    teste("Cliente teste localizado", cliente is not None)

    cliente_id = cliente["id"] if cliente else None

    marcacao1 = con.execute("""
        SELECT id, cliente_id, inicio, duracao_minutos,
               estado, observacoes
        FROM marcacoes
        WHERE cliente_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (cliente_id,)).fetchone()

    teste(
        "Campos da marcação guardados",
        marcacao1 is not None
        and marcacao1["duracao_minutos"] == 30
        and marcacao1["observacoes"] == "Teste automático"
    )

    marcacao1_id = marcacao1["id"]
    con.close()

    # -----------------------------------------------------
    # 6. API CLIENTE POR TELEFONE
    # -----------------------------------------------------
    r = client.get(
        "/api/clientes/por-telefone",
        query_string={"telefone": "+351 910 000 001"}
    )

    dados = r.get_json(silent=True) or {}

    teste(
        "API telefone encontra cliente",
        r.status_code == 200
        and dados.get("encontrado") is True
        and dados.get("cliente", {}).get("id") == cliente_id,
        str(dados)
    )

    r = client.get(
        "/api/clientes/por-telefone",
        query_string={"telefone": "+351 999 999 999"}
    )
    dados = r.get_json(silent=True) or {}

    teste(
        "API telefone desconhecido não inventa cliente",
        r.status_code == 200 and dados.get("encontrado") is False,
        str(dados)
    )

    # -----------------------------------------------------
    # 7. REUTILIZAÇÃO DO CLIENTE PELO TELEFONE
    # -----------------------------------------------------
    inicio2_dt = futuro + timedelta(hours=2)
    inicio2 = inicio2_dt.strftime("%Y-%m-%dT%H:%M")

    con = db()
    total_cliente_antes = con.execute(
        "SELECT COUNT(*) FROM clientes WHERE id = ?", (cliente_id,)
    ).fetchone()[0]
    total_telefone_antes = con.execute(
        "SELECT COUNT(*) FROM telefones WHERE cliente_id = ?", (cliente_id,)
    ).fetchone()[0]
    con.close()

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "TESTE AUTOMATICO A ATUALIZADO",
            "telefone": "+351910000001",
            "email": "novo-email@example.invalid",
            "inicio": inicio2,
            "duracao": "45",
            "servico": "Barba",
        },
        follow_redirects=False,
    )

    teste(
        "Segunda marcação com mesmo telefone aceite",
        r.status_code in (302, 303),
        f"HTTP {r.status_code}"
    )

    con = db()

    ids = con.execute("""
        SELECT DISTINCT c.id
        FROM clientes c
        JOIN telefones t ON t.cliente_id = c.id
        WHERE t.numero_normalizado = ?
    """, (appmod.normalizar_telefone(telefone),)).fetchall()

    teste(
        "Mesmo telefone reutiliza ficha",
        len(ids) == 1 and ids[0]["id"] == cliente_id,
        str([dict(x) for x in ids])
    )

    total_telefone_depois = con.execute(
        "SELECT COUNT(*) FROM telefones WHERE cliente_id = ?", (cliente_id,)
    ).fetchone()[0]

    teste(
        "Não duplicou telefone do cliente",
        total_telefone_depois == total_telefone_antes,
        f"{total_telefone_antes} -> {total_telefone_depois}"
    )

    dados_cliente = con.execute(
        "SELECT nome, email FROM clientes WHERE id = ?",
        (cliente_id,)
    ).fetchone()

    teste(
        "Ficha existente foi atualizada",
        dados_cliente["nome"] == "TESTE AUTOMATICO A ATUALIZADO"
        and dados_cliente["email"] == "novo-email@example.invalid",
        str(dict(dados_cliente))
    )

    con.close()

    # -----------------------------------------------------
    # 8. DISPONIBILIDADE / CONFLITOS
    # -----------------------------------------------------
    r = client.get(
        "/api/disponibilidade",
        query_string={
            "data": futuro.strftime("%Y-%m-%d"),
            "hora": "10:15",
            "duracao": "30"
        }
    )
    dados = r.get_json(silent=True) or {}

    teste(
        "API deteta conflito parcial",
        r.status_code == 200
        and dados.get("disponivel") is False
        and len(dados.get("conflitos", [])) >= 1,
        str(dados)
    )

    r = client.get(
        "/api/disponibilidade",
        query_string={
            "data": futuro.strftime("%Y-%m-%d"),
            "hora": "15:00",
            "duracao": "30"
        }
    )
    dados = r.get_json(silent=True) or {}

    teste(
        "API aceita horário livre",
        r.status_code == 200 and dados.get("disponivel") is True,
        str(dados)
    )

    # Tentativa real de conflito
    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "CONFLITO TESTE",
            "telefone": "+351910000002",
            "inicio": futuro.replace(minute=15).strftime("%Y-%m-%dT%H:%M"),
            "duracao": "30",
            "servico": "Corte",
        }
    )

    teste(
        "POST impede marcação sobreposta",
        r.status_code == 409,
        f"HTTP {r.status_code}"
    )

    # -----------------------------------------------------
    # 9. VALIDAÇÕES DE FORMULÁRIO
    # -----------------------------------------------------
    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "",
            "telefone": "",
            "inicio": inicio1,
            "duracao": "30",
            "servico": "Corte",
        }
    )
    teste(
        "Rejeita dados obrigatórios em falta",
        r.status_code == 400,
        f"HTTP {r.status_code}"
    )

    r = client.post(
        "/marcacoes/nova",
        data={
            "nome": "Teste",
            "telefone": "+351910000003",
            "inicio": inicio1,
            "duracao": "22",
            "servico": "Corte",
        }
    )
    teste(
        "Rejeita duração não permitida",
        r.status_code == 400,
        f"HTTP {r.status_code}"
    )

    r = client.get(
        "/api/disponibilidade",
        query_string={"data": "xxxx", "hora": "99:99", "duracao": "30"}
    )
    teste(
        "API rejeita data/hora inválidas",
        r.status_code == 400,
        f"HTTP {r.status_code}"
    )

    # -----------------------------------------------------
    # 10. ESTADOS DA MARCAÇÃO
    # -----------------------------------------------------
    for estado in ["faltou", "marcada", "cancelada", "concluída"]:
        r = client.post(
            f"/marcacoes/{marcacao1_id}/estado",
            data={"estado": estado},
            follow_redirects=False
        )

        con = db()
        estado_db = con.execute(
            "SELECT estado FROM marcacoes WHERE id = ?",
            (marcacao1_id,)
        ).fetchone()["estado"]
        con.close()

        teste(
            f"Alterar estado para {estado}",
            r.status_code in (302, 303) and estado_db == estado,
            f"HTTP={r.status_code}, DB={estado_db}"
        )

    r = client.post(
        f"/marcacoes/{marcacao1_id}/estado",
        data={"estado": "estado-inventado"}
    )
    teste(
        "Rejeita estado inválido",
        r.status_code == 400,
        f"HTTP {r.status_code}"
    )

    r = client.post(
        "/marcacoes/999999/estado",
        data={"estado": "concluída"}
    )
    teste(
        "Marcação inexistente devolve 404",
        r.status_code == 404,
        f"HTTP {r.status_code}"
    )

    # -----------------------------------------------------
    # 11. PESQUISA DE CLIENTES
    # -----------------------------------------------------
    r = client.get(
        "/clientes",
        query_string={"q": "TESTE AUTOMATICO A ATUALIZADO"}
    )

    teste(
        "Pesquisa por nome encontra cliente",
        r.status_code == 200
        and b"TESTE AUTOMATICO A ATUALIZADO" in r.data
    )

    r = client.get(
        "/clientes",
        query_string={"q": "910000001"}
    )

    teste(
        "Pesquisa por telefone encontra cliente",
        r.status_code == 200
        and b"TESTE AUTOMATICO A ATUALIZADO" in r.data
    )

    # -----------------------------------------------------
    # 12. FICHA / HISTÓRICO
    # -----------------------------------------------------
    r = client.get(f"/clientes/{cliente_id}")

    teste(
        "Ficha do cliente abre",
        r.status_code == 200
        and b"TESTE AUTOMATICO A ATUALIZADO" in r.data,
        f"HTTP {r.status_code}"
    )

    # -----------------------------------------------------
    # 13. CLIENTE INATIVO E ALERTA VISTO
    # -----------------------------------------------------
    antigo = datetime.now() - timedelta(days=100)

    con = db()
    con.execute(
        """
        UPDATE marcacoes
        SET inicio = ?, estado = 'concluída'
        WHERE id = ?
        """,
        (antigo.strftime("%Y-%m-%dT10:00"), marcacao1_id)
    )

    # Tornar também a segunda marcação antiga para não haver visita recente
    con.execute(
        """
        UPDATE marcacoes
        SET inicio = ?, estado = 'concluída'
        WHERE cliente_id = ? AND id != ?
        """,
        ((antigo + timedelta(days=1)).strftime("%Y-%m-%dT12:00"),
         cliente_id, marcacao1_id)
    )

    con.execute(
        "UPDATE clientes SET alerta_inatividade_visto_em = NULL WHERE id = ?",
        (cliente_id,)
    )
    con.commit()

    inativos = appmod.obter_clientes_inativos(
        con, dias=60, apenas_pendentes=True
    )
    ids_inativos = [x["id"] for x in inativos]

    teste(
        "Cliente antigo aparece como inativo",
        cliente_id in ids_inativos,
        str(ids_inativos)
    )
    con.close()

    # Abrir ficha deve marcar alerta como visto
    r = client.get(f"/clientes/{cliente_id}")
    teste("Abrir ficha do inativo responde 200", r.status_code == 200)

    con = db()
    visto = con.execute(
        """
        SELECT alerta_inatividade_visto_em
        FROM clientes
        WHERE id = ?
        """,
        (cliente_id,)
    ).fetchone()[0]

    pendentes = appmod.obter_clientes_inativos(
        con, dias=60, apenas_pendentes=True
    )
    ids_pendentes = [x["id"] for x in pendentes]

    teste(
        "Abrir ficha marca alerta como visto",
        visto is not None
    )

    teste(
        "Alerta visto deixa de estar pendente",
        cliente_id not in ids_pendentes,
        str(ids_pendentes)
    )

    todos_inativos = appmod.obter_clientes_inativos(
        con, dias=60, apenas_pendentes=False
    )
    ids_todos = [x["id"] for x in todos_inativos]

    teste(
        "Cliente continua na lista de inativos",
        cliente_id in ids_todos,
        str(ids_todos)
    )

    con.close()

    # -----------------------------------------------------
    # 14. TOP 10
    # -----------------------------------------------------
    r = client.get("/clientes?top=10")
    teste(
        "Página Top 10 responde",
        r.status_code == 200,
        f"HTTP {r.status_code}"
    )

    # Cliente sem concluídas não deve aparecer no Top 10
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO clientes (nome, email) VALUES (?, ?)",
        ("ZERO VISITAS AUTOMATICO", None)
    )
    zero_id = cur.lastrowid
    cur.execute(
        """
        INSERT INTO telefones
        (cliente_id, numero, numero_normalizado)
        VALUES (?, ?, ?)
        """,
        (zero_id, "+351910000099", "+351910000099")
    )
    con.commit()
    con.close()

    r = client.get("/clientes?top=10")
    teste(
        "Top 10 exclui cliente com zero concluídas",
        b"ZERO VISITAS AUTOMATICO" not in r.data
    )

    # -----------------------------------------------------
    # 15. CANCELADA LIBERTA O HORÁRIO
    # -----------------------------------------------------
    con = db()
    con.execute(
        """
        UPDATE marcacoes
        SET inicio = ?, estado = 'cancelada'
        WHERE id = ?
        """,
        (futuro.strftime("%Y-%m-%dT10:00"), marcacao1_id)
    )
    con.commit()
    con.close()

    r = client.get(
        "/api/disponibilidade",
        query_string={
            "data": futuro.strftime("%Y-%m-%d"),
            "hora": "10:00",
            "duracao": "30"
        }
    )

    dados = r.get_json(silent=True) or {}

    teste(
        "Marcação cancelada deixa de bloquear horário",
        r.status_code == 200 and dados.get("disponivel") is True,
        str(dados)
    )

    # -----------------------------------------------------
    # 16. EDITAR DURAÇÃO DE UMA MARCAÇÃO
    # -----------------------------------------------------

    # Duas marcações próprias para estes testes:
    # alvo 10:00-10:30 e seguinte 11:00-11:30.
    con = db()

    cur = con.execute(
        """
        INSERT INTO marcacoes
        (cliente_id, inicio, duracao_minutos, servico, estado, observacoes)
        VALUES (?, ?, ?, ?, 'marcada', ?)
        """,
        (cliente_id, "2030-01-15T10:00", 30, "", "Teste edição duração")
    )
    duracao_alvo_id = cur.lastrowid

    con.execute(
        """
        INSERT INTO marcacoes
        (cliente_id, inicio, duracao_minutos, servico, estado, observacoes)
        VALUES (?, ?, ?, ?, 'marcada', ?)
        """,
        (cliente_id, "2030-01-15T11:00", 30, "", "Teste conflito duração")
    )

    con.commit()
    con.close()

    # 16.1 — Alteração normal: 30 -> 45 minutos.
    # Continua a terminar às 10:45, portanto não existe conflito.
    r = client.post(
        f"/marcacoes/{duracao_alvo_id}/duracao",
        data={"duracao": "45"}
    )
    dados = r.get_json(silent=True) or {}

    con = db()
    duracao_guardada = con.execute(
        "SELECT duracao_minutos FROM marcacoes WHERE id = ?",
        (duracao_alvo_id,)
    ).fetchone()["duracao_minutos"]
    con.close()

    teste(
        "Editar duração sem conflito",
        r.status_code == 200
        and dados.get("ok") is True
        and duracao_guardada == 45,
        f"status={r.status_code}, dados={dados}, duração={duracao_guardada}"
    )

    # 16.2 — Duração fora das opções permitidas.
    r = client.post(
        f"/marcacoes/{duracao_alvo_id}/duracao",
        data={"duracao": "999"}
    )

    con = db()
    duracao_guardada = con.execute(
        "SELECT duracao_minutos FROM marcacoes WHERE id = ?",
        (duracao_alvo_id,)
    ).fetchone()["duracao_minutos"]
    con.close()

    teste(
        "Editar duração rejeita valor inválido",
        r.status_code == 400 and duracao_guardada == 45,
        f"status={r.status_code}, duração={duracao_guardada}"
    )

    # 16.3 — 90 minutos faria a primeira marcação terminar às 11:30,
    # sobrepondo 30 minutos da marcação seguinte.
    # Sem confirmação deve devolver 409 e NÃO alterar a base.
    r = client.post(
        f"/marcacoes/{duracao_alvo_id}/duracao",
        data={"duracao": "90"}
    )
    dados = r.get_json(silent=True) or {}

    con = db()
    duracao_guardada = con.execute(
        "SELECT duracao_minutos FROM marcacoes WHERE id = ?",
        (duracao_alvo_id,)
    ).fetchone()["duracao_minutos"]
    con.close()

    teste(
        "Editar duração deteta conflito sem alterar BD",
        r.status_code == 409
        and dados.get("requer_confirmacao") is True
        and len(dados.get("conflitos", [])) >= 1
        and duracao_guardada == 45,
        f"status={r.status_code}, dados={dados}, duração={duracao_guardada}"
    )

    # 16.4 — O mesmo conflito confirmado pelo utilizador deve ser aceite.
    r = client.post(
        f"/marcacoes/{duracao_alvo_id}/duracao",
        data={"duracao": "90", "forcar": "1"}
    )
    dados = r.get_json(silent=True) or {}

    con = db()
    duracao_guardada = con.execute(
        "SELECT duracao_minutos FROM marcacoes WHERE id = ?",
        (duracao_alvo_id,)
    ).fetchone()["duracao_minutos"]
    con.close()

    teste(
        "Editar duração permite conflito confirmado",
        r.status_code == 200
        and dados.get("ok") is True
        and duracao_guardada == 90,
        f"status={r.status_code}, dados={dados}, duração={duracao_guardada}"
    )

    # -----------------------------------------------------
    # 17. INTEGRIDADE FINAL DA CÓPIA
    # -----------------------------------------------------
    con = db()
    integrity_final = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()

    teste(
        "SQLite continua íntegro após todos os testes",
        integrity_final == "ok",
        integrity_final
    )

hash_depois = sha256(REAL_DB)

print()
print("==============================================")
print("                  RESULTADO")
print("==============================================")
print(f"PASS: {PASS}")
print(f"FAIL: {FAIL}")
print()

if hash_antes == hash_depois:
    print("✅ BASE REAL NÃO FOI ALTERADA")
else:
    print("❌ ATENÇÃO: HASH DA BASE REAL MUDOU")
    FAIL += 1

print("SHA antes :", hash_antes)
print("SHA depois:", hash_depois)
print()

if FAIL:
    print("❌ BATERIA TERMINOU COM FALHAS")
    sys.exit(1)

print("✅ TODOS OS TESTES PASSARAM")
sys.exit(0)
