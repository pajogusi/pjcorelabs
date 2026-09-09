import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

DB = Path(__file__).with_name("blessed.db")


def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@app.route("/")
def home():
    data_pedida = request.args.get("data")

    try:
        data_selecionada = (
            datetime.strptime(data_pedida, "%Y-%m-%d").date()
            if data_pedida
            else date.today()
        )
    except ValueError:
        data_selecionada = date.today()

    dia_anterior = data_selecionada - timedelta(days=1)
    dia_seguinte = data_selecionada + timedelta(days=1)

    hoje = date.today()

    if data_selecionada == hoje:
        titulo_dia = "Hoje"
    elif data_selecionada == hoje + timedelta(days=1):
        titulo_dia = "Amanhã"
    elif data_selecionada == hoje - timedelta(days=1):
        titulo_dia = "Ontem"
    else:
        dias_semana = [
            "Segunda-feira",
            "Terça-feira",
            "Quarta-feira",
            "Quinta-feira",
            "Sexta-feira",
            "Sábado",
            "Domingo",
        ]
        titulo_dia = dias_semana[data_selecionada.weekday()]

    con = get_db()

    marcacoes = con.execute("""
        SELECT
            m.id,
            m.inicio,
            m.duracao_minutos,
            m.servico,
            m.estado,
            c.nome
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) = ?
          AND m.estado != 'cancelada'
        ORDER BY m.inicio
    """, (data_selecionada.isoformat(),)).fetchall()

    con.close()

    total_marcacoes = len(marcacoes)
    marcacoes_concluidas = sum(
        1 for m in marcacoes if m["estado"] == "concluída"
    )

    # Horário provisório. Mais tarde virá das Definições.
    abertura = datetime.combine(
        data_selecionada,
        datetime.strptime("08:30", "%H:%M").time()
    )
    fecho = datetime.combine(
        data_selecionada,
        datetime.strptime("21:00", "%H:%M").time()
    )

    blocos = []
    cursor = abertura

    for m in marcacoes:
        inicio_m = datetime.fromisoformat(m["inicio"])
        fim_m = inicio_m + timedelta(minutes=m["duracao_minutos"])

        if cursor < inicio_m:
            livre = cursor

            while livre < inicio_m:
                fim_livre = min(
                    livre + timedelta(minutes=30),
                    inicio_m
                )

                blocos.append({
                    "tipo": "disponivel",
                    "inicio": livre,
                    "fim": fim_livre
                })

                livre = fim_livre

        blocos.append({
            "tipo": "marcacao",
            "inicio": inicio_m,
            "fim": fim_m,
            "id": m["id"],
            "nome": m["nome"],
            "servico": m["servico"],
            "estado": m["estado"]
        })

        if fim_m > cursor:
            cursor = fim_m

    if cursor < fecho:
        livre = cursor

        while livre < fecho:
            fim_livre = min(
                livre + timedelta(minutes=30),
                fecho
            )

            blocos.append({
                "tipo": "disponivel",
                "inicio": livre,
                "fim": fim_livre
            })

            livre = fim_livre

    return render_template(
        "index.html",
        marcacoes=marcacoes,
        blocos=blocos,
        data_selecionada=data_selecionada,
        hoje=date.today(),
        dia_anterior=dia_anterior,
        dia_seguinte=dia_seguinte,
        titulo_dia=titulo_dia,
        total_marcacoes=total_marcacoes,
        marcacoes_concluidas=marcacoes_concluidas
    )


@app.route("/marcacoes/nova", methods=["POST"])
def nova_marcacao():
    nome = request.form["nome"].strip()
    telefone = request.form["telefone"].strip()
    inicio = request.form["inicio"].strip()
    servico = request.form["servico"].strip()
    duracao = int(request.form.get("duracao", 30))
    forcar = request.form.get("forcar") == "1"

    if not nome or not telefone or not inicio or not servico:
        return "Dados obrigatórios em falta", 400

    novo_inicio = datetime.fromisoformat(inicio)
    novo_fim = novo_inicio + timedelta(minutes=duracao)

    con = get_db()

    conflitos = con.execute("""
        SELECT
            m.inicio,
            m.duracao_minutos,
            m.servico,
            c.nome
        FROM marcacoes m
        JOIN clientes c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) = ?
          AND m.estado != 'cancelada'
        ORDER BY m.inicio
    """, (novo_inicio.date().isoformat(),)).fetchall()

    conflitos_reais = []

    for m in conflitos:
        existente_inicio = datetime.fromisoformat(m["inicio"])
        existente_fim = existente_inicio + timedelta(
            minutes=m["duracao_minutos"]
        )

        if novo_inicio < existente_fim and novo_fim > existente_inicio:
            conflitos_reais.append({
                "nome": m["nome"],
                "inicio": existente_inicio.strftime("%H:%M"),
                "fim": existente_fim.strftime("%H:%M"),
                "servico": m["servico"]
            })

    if conflitos_reais and not forcar:
        con.close()

        linhas = "".join(
            f"<li><strong>{c['inicio']}–{c['fim']}</strong> — "
            f"{c['nome']} — {c['servico']}</li>"
            for c in conflitos_reais
        )

        return f"""
        <!doctype html>
        <html lang="pt">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Conflito — Blessed</title>
        </head>
        <body style="
            background:#080808;
            color:#fff;
            font-family:Arial,sans-serif;
            padding:24px;
            max-width:600px;
            margin:auto;
        ">
            <h2>⚠️ Sobreposição de horário</h2>
            <p>Esta marcação coincide com:</p>
            <ul>{linhas}</ul>

            <form method="post" action="/marcacoes/nova">
                <input type="hidden" name="nome" value="{nome}">
                <input type="hidden" name="telefone" value="{telefone}">
                <input type="hidden" name="inicio" value="{inicio}">
                <input type="hidden" name="servico" value="{servico}">
                <input type="hidden" name="duracao" value="{duracao}">
                <input type="hidden" name="forcar" value="1">

                <button type="button" onclick="history.back()">
                    Voltar
                </button>

                <button type="submit">
                    Marcar na mesma
                </button>
            </form>
        </body>
        </html>
        """

    numero_normalizado = "".join(
        c for c in telefone
        if c.isdigit() or c == "+"
    )

    try:
        cur = con.cursor()

        cur.execute("""
            INSERT INTO clientes (nome)
            VALUES (?)
        """, (nome,))
        cliente_id = cur.lastrowid

        cur.execute("""
            INSERT INTO telefones
            (cliente_id, numero, numero_normalizado)
            VALUES (?, ?, ?)
        """, (
            cliente_id,
            telefone,
            numero_normalizado
        ))

        cur.execute("""
            INSERT INTO marcacoes
            (cliente_id, inicio, duracao_minutos, servico)
            VALUES (?, ?, ?, ?)
        """, (
            cliente_id,
            inicio,
            duracao,
            servico
        ))

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()

    return redirect(
        url_for("home", data=novo_inicio.date().isoformat())
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
