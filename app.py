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
        data_selecionada = datetime.strptime(data_pedida, "%Y-%m-%d").date() if data_pedida else date.today()
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
        dias_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
        titulo_dia = dias_semana[data_selecionada.weekday()]

    con = get_db()
    marcacoes = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.servico, m.estado, c.nome
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) = ? AND m.estado != 'cancelada'
        ORDER BY m.inicio
    """, (data_selecionada.isoformat(),)).fetchall()
    con.close()

    total_marcacoes = len(marcacoes)
    marcacoes_concluidas = sum(1 for m in marcacoes if m["estado"] == "concluída")
    abertura = datetime.combine(data_selecionada, datetime.strptime("08:30", "%H:%M").time())
    fecho = datetime.combine(data_selecionada, datetime.strptime("21:00", "%H:%M").time())
    blocos = []
    cursor = abertura

    for m in marcacoes:
        inicio_m = datetime.fromisoformat(m["inicio"])
        fim_m = inicio_m + timedelta(minutes=m["duracao_minutos"])
        if cursor < inicio_m:
            livre = cursor
            while livre < inicio_m:
                fim_livre = min(livre + timedelta(minutes=30), inicio_m)
                blocos.append({"tipo": "disponivel", "inicio": livre, "fim": fim_livre})
                livre = fim_livre
        blocos.append({"tipo": "marcacao", "inicio": inicio_m, "fim": fim_m, "id": m["id"], "nome": m["nome"], "servico": m["servico"], "estado": m["estado"]})
        if fim_m > cursor:
            cursor = fim_m

    if cursor < fecho:
        livre = cursor
        while livre < fecho:
            fim_livre = min(livre + timedelta(minutes=30), fecho)
            blocos.append({"tipo": "disponivel", "inicio": livre, "fim": fim_livre})
            livre = fim_livre

    return render_template("index.html", marcacoes=marcacoes, blocos=blocos, data_selecionada=data_selecionada, hoje=date.today(), dia_anterior=dia_anterior, dia_seguinte=dia_seguinte, titulo_dia=titulo_dia, total_marcacoes=total_marcacoes, marcacoes_concluidas=marcacoes_concluidas)


@app.route("/semana")
def semana():
    data_pedida = request.args.get("data")
    try:
        referencia = datetime.strptime(data_pedida, "%Y-%m-%d").date() if data_pedida else date.today()
    except ValueError:
        referencia = date.today()

    inicio_semana = referencia - timedelta(days=referencia.weekday())
    fim_semana = inicio_semana + timedelta(days=6)
    semana_anterior = inicio_semana - timedelta(days=7)
    semana_seguinte = inicio_semana + timedelta(days=7)

    con = get_db()
    marcacoes = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.servico, m.estado, c.nome
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) BETWEEN ? AND ? AND m.estado != 'cancelada'
        ORDER BY m.inicio
    """, (inicio_semana.isoformat(), fim_semana.isoformat())).fetchall()
    con.close()

    dias = []
    nomes_dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    for numero in range(7):
        data_dia = inicio_semana + timedelta(days=numero)
        marcacoes_dia = []
        for m in marcacoes:
            if m["inicio"][:10] != data_dia.isoformat():
                continue
            inicio_m = datetime.fromisoformat(m["inicio"])
            minuto_base = 30 if inicio_m.minute >= 30 else 0
            hora_base = inicio_m.replace(minute=minuto_base, second=0, microsecond=0)
            deslocamento = inicio_m.minute - minuto_base
            marcacoes_dia.append({
                "id": m["id"],
                "inicio": m["inicio"],
                "hora": inicio_m.strftime("%H:%M"),
                "hora_base": hora_base.strftime("%H:%M"),
                "deslocamento": deslocamento,
                "duracao": m["duracao_minutos"],
                "servico": m["servico"],
                "estado": m["estado"],
                "nome": m["nome"]
            })
        dias.append({"data": data_dia.isoformat(), "nome": nomes_dias[numero], "marcacoes": marcacoes_dia})

    horas_grelha = []
    hora_atual = datetime.strptime("08:00", "%H:%M")
    hora_fim = datetime.strptime("23:00", "%H:%M")
    while hora_atual < hora_fim:
        horas_grelha.append(hora_atual.strftime("%H:%M"))
        hora_atual += timedelta(minutes=30)

    return render_template("semana.html", inicio_semana=inicio_semana, fim_semana=fim_semana, semana_anterior=semana_anterior, semana_seguinte=semana_seguinte, dias=dias, horas_grelha=horas_grelha)


@app.route("/api/disponibilidade")
def disponibilidade():
    data_pedida = request.args.get("data", "").strip()
    hora_pedida = request.args.get("hora", "").strip()
    try:
        duracao = int(request.args.get("duracao", 30))
        if duracao not in (15, 30, 60, 90):
            raise ValueError
        inicio = datetime.fromisoformat(f"{data_pedida}T{hora_pedida}")
    except (ValueError, TypeError):
        return {"ok": False, "erro": "Data, hora ou duração inválida"}, 400

    fim = inicio + timedelta(minutes=duracao)
    con = get_db()
    marcacoes = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.servico, c.nome
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) = ? AND m.estado != 'cancelada'
        ORDER BY m.inicio
    """, (inicio.date().isoformat(),)).fetchall()
    con.close()

    conflitos = []
    for m in marcacoes:
        existente_inicio = datetime.fromisoformat(m["inicio"])
        existente_fim = existente_inicio + timedelta(minutes=m["duracao_minutos"])
        if inicio < existente_fim and fim > existente_inicio:
            conflitos.append({"id": m["id"], "nome": m["nome"], "servico": m["servico"], "inicio": existente_inicio.strftime("%H:%M"), "fim": existente_fim.strftime("%H:%M")})

    return {"ok": True, "disponivel": len(conflitos) == 0, "data": inicio.date().isoformat(), "inicio": inicio.strftime("%H:%M"), "fim": fim.strftime("%H:%M"), "duracao": duracao, "conflitos": conflitos}


@app.route("/marcacoes/nova", methods=["POST"])
def nova_marcacao():
    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    inicio = request.form.get("inicio", "").strip()
    servico = request.form.get("servico", "").strip()
    try:
        duracao = int(request.form.get("duracao", 30))
        novo_inicio = datetime.fromisoformat(inicio)
    except (ValueError, TypeError):
        return "Data, hora ou duração inválida", 400

    if not nome or not telefone or not inicio or not servico or duracao not in (15, 30, 60, 90):
        return "Dados obrigatórios em falta", 400

    novo_fim = novo_inicio + timedelta(minutes=duracao)
    con = get_db()
    conflitos = con.execute("""
        SELECT m.inicio, m.duracao_minutos
        FROM marcacoes m
        WHERE substr(m.inicio, 1, 10) = ? AND m.estado != 'cancelada'
    """, (novo_inicio.date().isoformat(),)).fetchall()

    for m in conflitos:
        existente_inicio = datetime.fromisoformat(m["inicio"])
        existente_fim = existente_inicio + timedelta(minutes=m["duracao_minutos"])
        if novo_inicio < existente_fim and novo_fim > existente_inicio:
            con.close()
            return "Horário ocupado", 409

    numero_normalizado = "".join(c for c in telefone if c.isdigit() or c == "+")
    try:
        cur = con.cursor()
        cur.execute("INSERT INTO clientes (nome) VALUES (?)", (nome,))
        cliente_id = cur.lastrowid
        cur.execute("INSERT INTO telefones (cliente_id, numero, numero_normalizado) VALUES (?, ?, ?)", (cliente_id, telefone, numero_normalizado))
        cur.execute("INSERT INTO marcacoes (cliente_id, inicio, duracao_minutos, servico) VALUES (?, ?, ?, ?)", (cliente_id, inicio, duracao, servico))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    return redirect(url_for("semana", data=novo_inicio.date().isoformat()))


@app.route("/marcacoes/<int:marcacao_id>/estado", methods=["POST"])
def alterar_estado_marcacao(marcacao_id):
    estado = request.form.get("estado", "").strip()
    estados_validos = {"marcada", "concluída", "cancelada", "faltou"}
    if estado not in estados_validos:
        return "Estado inválido", 400

    con = get_db()
    marcacao = con.execute("SELECT id, inicio FROM marcacoes WHERE id = ?", (marcacao_id,)).fetchone()
    if not marcacao:
        con.close()
        return "Marcação não encontrada", 404

    con.execute(
        "UPDATE marcacoes SET estado = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (estado, marcacao_id),
    )
    con.commit()
    data_marcacao = marcacao["inicio"][:10]
    con.close()

    return redirect(url_for("semana", data=data_marcacao))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
