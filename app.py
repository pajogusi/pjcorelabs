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


def normalizar_telefone(numero):
    numero = (numero or "").strip()
    return "".join(c for c in numero if c.isdigit() or c == "+")


@app.template_filter("data_pt")
def data_pt(valor):
    """Apresenta datas ISO em DD/MM/AAAA sem alterar o valor guardado na base."""
    if not valor:
        return "—"
    try:
        texto = str(valor)
        return datetime.fromisoformat(texto).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return valor


def garantir_esquema():
    """Aplica pequenas migrações compatíveis sem apagar dados existentes."""
    con = get_db()
    colunas = {row["name"] for row in con.execute("PRAGMA table_info(marcacoes)")}
    if "observacoes" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN observacoes TEXT")

    colunas_clientes = {row["name"] for row in con.execute("PRAGMA table_info(clientes)")}
    if "alerta_inatividade_visto_em" not in colunas_clientes:
        con.execute("ALTER TABLE clientes ADD COLUMN alerta_inatividade_visto_em TEXT")

    con.commit()
    con.close()


def concretizar_marcacoes_vencidas(con):
    """Concretiza por defeito marcações ainda 'marcada' 10 min após a hora de início."""
    limite = datetime.now() - timedelta(minutes=10)
    con.execute(
        """
        UPDATE marcacoes
        SET estado = 'concluída', atualizado_em = CURRENT_TIMESTAMP
        WHERE estado = 'marcada' AND inicio <= ?
        """,
        (limite.strftime("%Y-%m-%dT%H:%M"),),
    )
    con.commit()


def obter_clientes_inativos(con, dias=60, apenas_pendentes=False):
    """Clientes inativos; opcionalmente só os alertas ainda não consultados."""
    limite = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M")
    return con.execute(
        """
        SELECT
            c.id,
            c.nome,
            c.email,
            c.alerta_inatividade_visto_em,
            COALESCE((
                SELECT t.numero
                FROM telefones t
                WHERE t.cliente_id = c.id AND t.atual = 1
                ORDER BY t.id DESC
                LIMIT 1
            ), '') AS telefone,
            MAX(CASE WHEN m.estado = 'concluída' THEN m.inicio END) AS ultimo_corte
        FROM clientes c
        JOIN marcacoes m ON m.cliente_id = c.id
        GROUP BY c.id
        HAVING ultimo_corte IS NOT NULL
           AND ultimo_corte <= ?
           AND (
                ? = 0
                OR c.alerta_inatividade_visto_em IS NULL
                OR c.alerta_inatividade_visto_em < ultimo_corte
           )
        ORDER BY ultimo_corte ASC
        """,
        (limite, 1 if apenas_pendentes else 0),
    ).fetchall()


@app.route("/")
def entrada():
    return render_template("entrada.html")


@app.route("/hoje")
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
    concretizar_marcacoes_vencidas(con)
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
    concretizar_marcacoes_vencidas(con)
    marcacoes = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.servico, m.estado, c.nome
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) BETWEEN ? AND ? AND m.estado != 'cancelada'
        ORDER BY m.inicio
    """, (inicio_semana.isoformat(), fim_semana.isoformat())).fetchall()
    clientes_inativos = obter_clientes_inativos(con, apenas_pendentes=True)
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

    return render_template(
        "semana.html",
        inicio_semana=inicio_semana,
        fim_semana=fim_semana,
        semana_anterior=semana_anterior,
        semana_seguinte=semana_seguinte,
        dias=dias,
        horas_grelha=horas_grelha,
        clientes_inativos=clientes_inativos,
    )


@app.route("/clientes")
def clientes():
    pesquisa = request.args.get("q", "").strip()
    apenas_inativos = request.args.get("inativos") == "1"
    top10 = request.args.get("top") == "10"
    termo = f"%{pesquisa}%"
    limite_inatividade = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M")
    con = get_db()
    clientes_lista = con.execute("""
        SELECT
            c.id,
            c.nome,
            c.email,
            c.data_nascimento,
            COALESCE((
                SELECT t.numero
                FROM telefones t
                WHERE t.cliente_id = c.id AND t.atual = 1
                ORDER BY t.id DESC
                LIMIT 1
            ), '') AS telefone,
            COUNT(m.id) AS total_marcacoes,
            SUM(CASE WHEN m.estado = 'concluída' THEN 1 ELSE 0 END) AS total_concluidas,
            MAX(CASE WHEN m.estado = 'concluída' THEN m.inicio END) AS ultimo_corte
        FROM clientes c
        LEFT JOIN telefones tp ON tp.cliente_id = c.id AND tp.atual = 1
        LEFT JOIN marcacoes m ON m.cliente_id = c.id
        WHERE (? = ''
           OR c.nome LIKE ? COLLATE NOCASE
           OR COALESCE(c.email, '') LIKE ? COLLATE NOCASE
           OR COALESCE(tp.numero, '') LIKE ?
           OR COALESCE(tp.numero_normalizado, '') LIKE ?)
        GROUP BY c.id
        HAVING (? = 0 OR (ultimo_corte IS NOT NULL AND ultimo_corte <= ?))
           AND (? = 0 OR SUM(CASE WHEN m.estado = 'concluída' THEN 1 ELSE 0 END) > 0)
        ORDER BY
            CASE WHEN ? = 1 THEN SUM(CASE WHEN m.estado = 'concluída' THEN 1 ELSE 0 END) END DESC,
            CASE WHEN ? = 1 THEN ultimo_corte END DESC,
            c.nome COLLATE NOCASE
        LIMIT CASE WHEN ? = 1 THEN 10 ELSE -1 END
    """, (
        pesquisa, termo, termo, termo, termo,
        1 if apenas_inativos else 0, limite_inatividade,
        1 if top10 else 0,
        1 if top10 else 0,
        1 if top10 else 0,
        1 if top10 else 0,
    )).fetchall()
    total_inativos = len(obter_clientes_inativos(con))
    con.close()
    return render_template(
        "clientes.html",
        clientes=clientes_lista,
        pesquisa=pesquisa,
        apenas_inativos=apenas_inativos,
        top10=top10,
        total_inativos=total_inativos,
    )


@app.route("/clientes/<int:cliente_id>")
def cliente_detalhe(cliente_id):
    con = get_db()
    cliente = con.execute("""
        SELECT
            c.*,
            COALESCE((
                SELECT t.numero
                FROM telefones t
                WHERE t.cliente_id = c.id AND t.atual = 1
                ORDER BY t.id DESC
                LIMIT 1
            ), '') AS telefone
        FROM clientes c
        WHERE c.id = ?
    """, (cliente_id,)).fetchone()
    if not cliente:
        con.close()
        return "Cliente não encontrado", 404

    historico = con.execute("""
        SELECT id, inicio, duracao_minutos, servico, estado, observacoes
        FROM marcacoes
        WHERE cliente_id = ?
        ORDER BY inicio DESC
    """, (cliente_id,)).fetchall()

    ultimo_corte = con.execute("""
        SELECT MAX(inicio)
        FROM marcacoes
        WHERE cliente_id = ? AND estado = 'concluída'
    """, (cliente_id,)).fetchone()[0]

    limite_inatividade = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M")
    if ultimo_corte and ultimo_corte <= limite_inatividade:
        con.execute("""
            UPDATE clientes
            SET alerta_inatividade_visto_em = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (cliente_id,))
        con.commit()

    con.close()
    return render_template("cliente.html", cliente=cliente, historico=historico)


@app.route("/api/clientes/por-telefone")
def cliente_por_telefone():
    numero = normalizar_telefone(request.args.get("telefone", ""))
    if not numero:
        return {"ok": True, "encontrado": False}

    con = get_db()
    cliente = con.execute("""
        SELECT c.id, c.nome, c.email, c.data_nascimento, t.numero
        FROM telefones t
        JOIN clientes c ON c.id = t.cliente_id
        WHERE t.numero_normalizado = ? AND t.atual = 1
        ORDER BY t.id DESC
        LIMIT 1
    """, (numero,)).fetchone()
    con.close()

    if not cliente:
        return {"ok": True, "encontrado": False}

    return {
        "ok": True,
        "encontrado": True,
        "cliente": {
            "id": cliente["id"],
            "nome": cliente["nome"],
            "telefone": cliente["numero"],
            "email": cliente["email"] or "",
            "data_nascimento": cliente["data_nascimento"] or "",
        },
    }


@app.route("/api/disponibilidade")
def disponibilidade():
    data_pedida = request.args.get("data", "").strip()
    hora_pedida = request.args.get("hora", "").strip()
    try:
        duracao = int(request.args.get("duracao", 30))
        if duracao not in (15, 30, 45, 60, 90):
            raise ValueError
        inicio = datetime.fromisoformat(f"{data_pedida}T{hora_pedida}")
    except (ValueError, TypeError):
        return {"ok": False, "erro": "Data, hora ou duração inválida"}, 400

    fim = inicio + timedelta(minutes=duracao)
    con = get_db()
    concretizar_marcacoes_vencidas(con)
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
    email = request.form.get("email", "").strip()
    data_nascimento = request.form.get("data_nascimento", "").strip() or None
    observacoes = request.form.get("observacoes", "").strip() or None
    inicio = request.form.get("inicio", "").strip()
    servico = request.form.get("servico", "").strip()
    try:
        duracao = int(request.form.get("duracao", 30))
        novo_inicio = datetime.fromisoformat(inicio)
    except (ValueError, TypeError):
        return "Data, hora ou duração inválida", 400

    if not nome or not telefone or not inicio or not servico or duracao not in (15, 30, 45, 60, 90):
        return "Dados obrigatórios em falta", 400

    novo_fim = novo_inicio + timedelta(minutes=duracao)
    numero_normalizado = normalizar_telefone(telefone)
    if not numero_normalizado:
        return "Número de telefone inválido", 400

    con = get_db()
    concretizar_marcacoes_vencidas(con)
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

    try:
        cur = con.cursor()
        cliente = cur.execute("""
            SELECT c.id
            FROM telefones t
            JOIN clientes c ON c.id = t.cliente_id
            WHERE t.numero_normalizado = ? AND t.atual = 1
            ORDER BY t.id DESC
            LIMIT 1
        """, (numero_normalizado,)).fetchone()

        if cliente:
            cliente_id = cliente["id"]
            cur.execute("""
                UPDATE clientes
                SET nome = ?,
                    email = CASE WHEN ? != '' THEN ? ELSE email END,
                    data_nascimento = COALESCE(?, data_nascimento),
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (nome, email, email, data_nascimento, cliente_id))
        else:
            cur.execute("""
                INSERT INTO clientes (nome, email, data_nascimento)
                VALUES (?, ?, ?)
            """, (nome, email or None, data_nascimento))
            cliente_id = cur.lastrowid
            cur.execute("""
                INSERT INTO telefones (cliente_id, numero, numero_normalizado)
                VALUES (?, ?, ?)
            """, (cliente_id, telefone, numero_normalizado))

        cur.execute("""
            INSERT INTO marcacoes
            (cliente_id, inicio, duracao_minutos, servico, observacoes)
            VALUES (?, ?, ?, ?, ?)
        """, (cliente_id, inicio, duracao, servico, observacoes))
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
    concretizar_marcacoes_vencidas(con)
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


garantir_esquema()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
