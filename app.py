import base64
import csv
import io
import json
import os
import secrets
import threading
import sqlite3
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("BLESSED_SECRET_KEY", "blessed-multiuser-test-only")

DB = Path(__file__).with_name("blessed.db")

LOG_EMAIL_DESTINO = "pajogusi.uk@gmail.com"
LOG_LOTE_TAMANHO = 10
LOG_LOCK = threading.Lock()



def enviar_email_brevo(destinatario, assunto, texto, anexo_nome=None, anexo_conteudo=None):
    """Envia email transacional pela Brevo. Devolve True/False sem interromper a aplicação."""
    destinatario = (destinatario or "").strip()
    if not destinatario:
        return False

    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    if not api_key:
        print("EMAIL: BREVO_API_KEY não configurada")
        return False

    payload = {
        "sender": {
            "name": "Blessed Barbearia Testes",
            "email": "pjgs.form@gmail.com",
        },
        "to": [
            {
                "email": destinatario,
            }
        ],
        "subject": assunto,
        "textContent": texto,
    }

    if anexo_nome and anexo_conteudo is not None:
        if isinstance(anexo_conteudo, str):
            anexo_conteudo = anexo_conteudo.encode("utf-8")

        payload["attachment"] = [{
            "name": anexo_nome,
            "content": base64.b64encode(anexo_conteudo).decode("ascii"),
        }]

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resposta:
            return 200 <= resposta.status < 300
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as erro:
        print(f"EMAIL: falha no envio Brevo: {erro}")
        return False



def enviar_sms_smsgate(telefone, texto):
    """Envia SMS através do SMSGate no Lenovo via Tailscale. Devolve True/False."""
    telefone = normalizar_telefone(telefone)
    texto = (texto or "").strip()

    if not telefone or not texto:
        return False

    env_path = Path.home() / ".config" / "blessed" / "smsgate.env"
    credenciais = {}

    try:
        for linha in env_path.read_text().splitlines():
            if "=" in linha:
                chave, valor = linha.split("=", 1)
                credenciais[chave.strip()] = valor.strip()
    except OSError as erro:
        print(f"SMS: não foi possível ler credenciais: {erro}")
        return False

    utilizador = credenciais.get("SMSGATE_USER", "")
    password = credenciais.get("SMSGATE_PASSWORD", "")

    if not utilizador or not password:
        print("SMS: credenciais SMSGate não configuradas")
        return False

    payload = {
        "textMessage": {
            "text": texto,
        },
        "phoneNumbers": [
            telefone,
        ],
    }

    token = __import__("base64").b64encode(
        f"{utilizador}:{password}".encode("utf-8")
    ).decode("ascii")

    req = urllib.request.Request(
        "http://100.108.198.2:8080/message",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resposta:
            return 200 <= resposta.status < 300
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as erro:
        print(f"SMS: falha no envio pelo SMSGate: {erro}")
        return False

def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def utilizador_atual():
    if "utilizador" not in g:
        utilizador_id = session.get("utilizador_id")
        if not utilizador_id:
            g.utilizador = None
        else:
            con = get_db()
            g.utilizador = con.execute(
                "SELECT id, nome, username, papel, ativo, pode_consultar_agendas, pode_marcar_outros FROM utilizadores WHERE id = ?",
                (utilizador_id,),
            ).fetchone()
            con.close()
    return g.utilizador


def gestor():
    utilizador = utilizador_atual()
    return bool(utilizador and utilizador["papel"] == "gestor")


def requer_login(func):
    @wraps(func)
    def protegido(*args, **kwargs):
        utilizador = utilizador_atual()
        if not utilizador or not utilizador["ativo"]:
            session.clear()
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return protegido


def requer_gestor(func):
    @wraps(func)
    @requer_login
    def protegido(*args, **kwargs):
        if not gestor():
            abort(403)
        return func(*args, **kwargs)
    return protegido


def barbeiro_permitido(barbeiro_id):
    """O gestor pode escolher qualquer profissional; o barbeiro apenas a si próprio."""
    utilizador = utilizador_atual()
    return bool(utilizador and (utilizador["papel"] == "gestor" or utilizador["id"] == barbeiro_id))


def pode_consultar_agenda(barbeiro_id):
    utilizador = utilizador_atual()
    return bool(utilizador and (
        utilizador["papel"] == "gestor"
        or utilizador["id"] == barbeiro_id
        or utilizador["pode_consultar_agendas"]
    ))


def pode_marcar_para(barbeiro_id):
    utilizador = utilizador_atual()
    return bool(utilizador and (
        utilizador["papel"] == "gestor"
        or utilizador["id"] == barbeiro_id
        or utilizador["pode_marcar_outros"]
    ))


def pode_alterar_marcacao(marcacao):
    """Só o gestor, o barbeiro responsável, ou quem a criou para outro pode alterar."""
    utilizador = utilizador_atual()
    return bool(utilizador and (
        utilizador["papel"] == "gestor"
        or marcacao["barbeiro_id"] == utilizador["id"]
        or (
            utilizador["pode_marcar_outros"]
            and marcacao["criado_por_id"] == utilizador["id"]
        )
    ))


def expirar_reservas_online(con, agora=None):
    """Liberta reservas online cujo sinal não foi pago em 15 minutos."""
    agora = agora or datetime.now().astimezone()
    con.execute("""
        UPDATE reservas_online
        SET estado = 'expirada'
        WHERE estado = 'aguarda_pagamento' AND expira_em <= ?
    """, (agora.isoformat(timespec="seconds"),))
    con.execute("""
        UPDATE pagamentos_online
        SET estado = 'expirado', atualizado_em = ?
        WHERE estado = 'pendente'
          AND reserva_id IN (SELECT id FROM reservas_online WHERE estado = 'expirada')
    """, (agora.isoformat(timespec="seconds"),))
    con.commit()


def barbeiro_livre_para_reserva(con, barbeiro_id, inicio, duracao_minutos):
    """Disponibilidade de um profissional, incluindo reservas a aguardar pagamento."""
    expirar_reservas_online(con)
    fim = inicio + timedelta(minutes=duracao_minutos)
    marcacoes = con.execute("""
        SELECT inicio, duracao_minutos FROM marcacoes
        WHERE barbeiro_id = ? AND estado != 'cancelada'
          AND substr(inicio, 1, 10) = ?
        UNION ALL
        SELECT inicio, duracao_minutos FROM reservas_online
        WHERE barbeiro_id = ? AND estado = 'aguarda_pagamento'
          AND substr(inicio, 1, 10) = ?
    """, (barbeiro_id, inicio.date().isoformat(), barbeiro_id, inicio.date().isoformat())).fetchall()
    for item in marcacoes:
        existente_inicio = datetime.fromisoformat(item["inicio"])
        existente_fim = existente_inicio + timedelta(minutes=item["duracao_minutos"])
        if inicio < existente_fim and fim > existente_inicio:
            return False
    return True


@app.before_request
def exigir_autenticacao():
    if request.endpoint in {"login", "logout", "online_reservar", "online_reservar_submeter", "online_reserva_pagamento", "static"}:
        return None
    utilizador = utilizador_atual()
    if not utilizador or not utilizador["ativo"]:
        session.clear()
        return redirect(url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        con = get_db()
        utilizador = con.execute(
            "SELECT id, password_hash, ativo FROM utilizadores WHERE username = ?",
            (username,),
        ).fetchone()
        con.close()
        if utilizador and utilizador["ativo"] and check_password_hash(utilizador["password_hash"], password):
            session.clear()
            session["utilizador_id"] = utilizador["id"]
            return redirect(url_for("semana"))
        return render_template("login.html", erro="Utilizador ou palavra-passe incorretos."), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/reservar")
def online_reservar():
    con = get_db()
    expirar_reservas_online(con)
    barbeiros = con.execute(
        "SELECT id, nome FROM utilizadores WHERE ativo = 1 ORDER BY nome COLLATE NOCASE"
    ).fetchall()
    con.close()
    return render_template(
        "reservar_online.html",
        barbeiros=barbeiros,
        servicos=["Corte", "Barba", "Corte + Barba"],
        hoje=date.today().isoformat(),
    )


@app.route("/reservar", methods=["POST"])
def online_reservar_submeter():
    nome = request.form.get("nome", "").strip()
    telefone = normalizar_telefone(request.form.get("telefone", ""))
    email = request.form.get("email", "").strip() or None
    servico = request.form.get("servico", "").strip()
    escolha = request.form.get("barbeiro", "").strip()
    try:
        inicio = datetime.fromisoformat(request.form.get("inicio", "").strip())
        duracao = int(request.form.get("duracao", "30"))
    except (TypeError, ValueError):
        return render_template("reservar_online.html", erro="Escolhe uma data e hora válidas."), 400
    if not nome or not telefone or servico not in {"Corte", "Barba", "Corte + Barba"} or duracao not in {15, 30, 45, 60, 90}:
        return render_template("reservar_online.html", erro="Preenche os dados obrigatórios."), 400

    con = get_db()
    expirar_reservas_online(con)
    barbeiros = con.execute("SELECT id, nome FROM utilizadores WHERE ativo = 1 ORDER BY nome COLLATE NOCASE").fetchall()
    if escolha == "primeiro":
        barbeiro = next((b for b in barbeiros if barbeiro_livre_para_reserva(con, b["id"], inicio, duracao)), None)
    else:
        barbeiro = next((b for b in barbeiros if str(b["id"]) == escolha), None)
        if barbeiro and not barbeiro_livre_para_reserva(con, barbeiro["id"], inicio, duracao):
            barbeiro = None
    if not barbeiro:
        con.close()
        return render_template("reservar_online.html", barbeiros=barbeiros, servicos=["Corte", "Barba", "Corte + Barba"], hoje=date.today().isoformat(), erro="Esse horário já não está disponível. Escolhe outro."), 409

    expira_em = datetime.now().astimezone() + timedelta(minutes=15)
    token = secrets.token_urlsafe(24)
    cur = con.execute("""
        INSERT INTO reservas_online
        (token_publico, barbeiro_id, inicio, duracao_minutos, servico, nome_cliente, telefone_cliente, email_cliente, expira_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (token, barbeiro["id"], inicio.isoformat(timespec="minutes"), duracao, servico, nome, telefone, email, expira_em.isoformat(timespec="seconds")))
    reserva_id = cur.lastrowid
    con.execute("INSERT INTO pagamentos_online (reserva_id) VALUES (?)", (reserva_id,))
    con.commit()
    con.close()
    return redirect(url_for("online_reserva_pagamento", token=token))


@app.route("/reservar/pagamento/<token>")
def online_reserva_pagamento(token):
    con = get_db()
    expirar_reservas_online(con)
    reserva = con.execute("""
        SELECT r.*, u.nome AS barbeiro, p.valor_pence, p.estado AS pagamento_estado
        FROM reservas_online r
        JOIN utilizadores u ON u.id = r.barbeiro_id
        JOIN pagamentos_online p ON p.reserva_id = r.id
        WHERE r.token_publico = ?
    """, (token,)).fetchone()
    con.close()
    if not reserva:
        abort(404)
    return render_template("pagamento_online.html", reserva=reserva)


def normalizar_telefone(numero):
    numero = (numero or "").strip()
    return "".join(c for c in numero if c.isdigit() or c == "+")


def normalizar_data_nascimento(valor):
    """Aceita formatos de data existentes e devolve sempre uma data ISO."""
    valor = (valor or "").strip()
    if not valor:
        return None

    formatos = (
        "%Y-%m-%d",
        "%Y%m%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
    )

    for formato in formatos:
        try:
            return datetime.strptime(valor, formato).date().isoformat()
        except ValueError:
            continue

    raise ValueError("Data de nascimento inválida")



def _enviar_lote_atividades(con):
    rows = con.execute("""
        SELECT id, criado_em, metodo, caminho, estado_http, ip
        FROM atividade_log
        WHERE enviado_em IS NULL
        ORDER BY id
        LIMIT ?
    """, (LOG_LOTE_TAMANHO,)).fetchall()

    if len(rows) < LOG_LOTE_TAMANHO:
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "ID",
        "Data/Hora",
        "Metodo",
        "Caminho",
        "HTTP",
        "IP",
    ])

    for row in rows:
        writer.writerow([
            row["id"],
            row["criado_em"],
            row["metodo"],
            row["caminho"],
            row["estado_http"],
            row["ip"] or "",
        ])

    agora = datetime.now().astimezone()
    nome = agora.strftime("blessed-atividades-%Y%m%d-%H%M%S.csv")

    enviado = enviar_email_brevo(
        LOG_EMAIL_DESTINO,
        "Blessed — log de 10 atividades",
        (
            "Segue em anexo o lote automático das últimas "
            f"{LOG_LOTE_TAMANHO} atividades registadas no Blessed."
        ),
        anexo_nome=nome,
        anexo_conteudo=buffer.getvalue().encode("utf-8-sig"),
    )

    if not enviado:
        return

    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)

    con.execute(
        f"""
        UPDATE atividade_log
        SET enviado_em = ?
        WHERE id IN ({placeholders})
        """,
        [agora.isoformat(timespec="seconds"), *ids],
    )
    con.commit()


@app.after_request
def registar_atividade_site(response):
    # A bateria automática nunca gera logs nem emails reais.
    if app.config.get("TESTING"):
        return response

    # Recursos estáticos não contam como atividade do utilizador.
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return response

    try:
        with LOG_LOCK:
            con = get_db()

            ip = (
                request.headers.get("CF-Connecting-IP")
                or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or request.remote_addr
                or ""
            )

            con.execute("""
                INSERT INTO atividade_log
                    (criado_em, metodo, caminho, estado_http, ip)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now().astimezone().isoformat(timespec="seconds"),
                request.method,
                request.path,
                int(response.status_code),
                ip,
            ))
            con.commit()

            _enviar_lote_atividades(con)
            con.close()

    except Exception as erro:
        # Uma falha do log nunca deve impedir o funcionamento do Blessed.
        print(f"LOG: falha ao registar/enviar atividade: {erro}")

    return response


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
    if "barbeiro_id" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN barbeiro_id INTEGER")
    if "criado_por_id" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN criado_por_id INTEGER")

    con.execute("""
        CREATE TABLE IF NOT EXISTS utilizadores (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            papel TEXT NOT NULL CHECK (papel IN ('gestor', 'barbeiro')),
            ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
            pode_consultar_agendas INTEGER NOT NULL DEFAULT 0 CHECK (pode_consultar_agendas IN (0, 1)),
            pode_marcar_outros INTEGER NOT NULL DEFAULT 0 CHECK (pode_marcar_outros IN (0, 1)),
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    colunas_utilizadores = {row["name"] for row in con.execute("PRAGMA table_info(utilizadores)")}
    if "pode_consultar_agendas" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN pode_consultar_agendas INTEGER NOT NULL DEFAULT 0")
    if "pode_marcar_outros" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN pode_marcar_outros INTEGER NOT NULL DEFAULT 0")
    con.execute("CREATE INDEX IF NOT EXISTS idx_marcacoes_barbeiro_inicio ON marcacoes (barbeiro_id, inicio)")

    # Reservas online ficam separadas das marcações confirmadas: só passam à
    # agenda depois da confirmação de pagamento pelo fornecedor escolhido.
    con.execute("""
        CREATE TABLE IF NOT EXISTS reservas_online (
            id INTEGER PRIMARY KEY,
            token_publico TEXT NOT NULL UNIQUE,
            barbeiro_id INTEGER NOT NULL,
            inicio TEXT NOT NULL,
            duracao_minutos INTEGER NOT NULL CHECK (duracao_minutos > 0),
            servico TEXT NOT NULL,
            nome_cliente TEXT NOT NULL,
            telefone_cliente TEXT NOT NULL,
            email_cliente TEXT,
            estado TEXT NOT NULL DEFAULT 'aguarda_pagamento'
                CHECK (estado IN ('aguarda_pagamento', 'paga', 'expirada', 'cancelada', 'reagendada')),
            expira_em TEXT NOT NULL,
            marcacao_id INTEGER UNIQUE,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (barbeiro_id) REFERENCES utilizadores(id),
            FOREIGN KEY (marcacao_id) REFERENCES marcacoes(id)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS pagamentos_online (
            id INTEGER PRIMARY KEY,
            reserva_id INTEGER NOT NULL UNIQUE,
            fornecedor TEXT,
            referencia_fornecedor TEXT UNIQUE,
            valor_pence INTEGER NOT NULL DEFAULT 1000 CHECK (valor_pence = 1000),
            moeda TEXT NOT NULL DEFAULT 'GBP',
            estado TEXT NOT NULL DEFAULT 'pendente'
                CHECK (estado IN ('pendente', 'autorizado', 'pago', 'falhou', 'reembolsado', 'expirado')),
            confirmado_em TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reserva_id) REFERENCES reservas_online(id)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_reservas_online_expira ON reservas_online (estado, expira_em)")

    colunas_clientes = {row["name"] for row in con.execute("PRAGMA table_info(clientes)")}
    if "alerta_inatividade_visto_em" not in colunas_clientes:
        con.execute("ALTER TABLE clientes ADD COLUMN alerta_inatividade_visto_em TEXT")

    con.execute("""
        CREATE TABLE IF NOT EXISTS definicoes (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        )
    """)
    con.execute("""
        INSERT OR IGNORE INTO definicoes (chave, valor)
        VALUES ('dias_inatividade', '60')
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS email_fila (
            id INTEGER PRIMARY KEY,
            cliente_id INTEGER NOT NULL,
            marcacao_id INTEGER,
            email_destino TEXT NOT NULL,
            tipo TEXT NOT NULL,
            assunto TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendente',
            tentativas INTEGER NOT NULL DEFAULT 0,
            previsto_para TEXT,
            idempotency_key TEXT UNIQUE,
            enviado_em TEXT,
            ultima_tentativa_em TEXT,
            erro TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS sms_fila (
            id INTEGER PRIMARY KEY,
            cliente_id INTEGER NOT NULL,
            marcacao_id INTEGER,
            telefone_destino TEXT NOT NULL,
            tipo TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendente',
            tentativas INTEGER NOT NULL DEFAULT 0,
            previsto_para TEXT,
            idempotency_key TEXT UNIQUE,
            enviado_em TEXT,
            ultima_tentativa_em TEXT,
            erro TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id),
            FOREIGN KEY (marcacao_id) REFERENCES marcacoes(id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS atividade_log (
            id INTEGER PRIMARY KEY,
            criado_em TEXT NOT NULL,
            metodo TEXT NOT NULL,
            caminho TEXT NOT NULL,
            estado_http INTEGER NOT NULL,
            ip TEXT,
            enviado_em TEXT
        )
    """)

    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_atividade_log_pendente
        ON atividade_log (enviado_em, id)
    """)

    con.commit()
    con.close()


def obter_definicao(con, chave, padrao=None):
    row = con.execute(
        "SELECT valor FROM definicoes WHERE chave = ?",
        (chave,)
    ).fetchone()
    return row["valor"] if row else padrao


def obter_dias_inatividade(con):
    try:
        valor = int(obter_definicao(con, "dias_inatividade", "60"))
        return valor if 15 <= valor <= 365 else 60
    except (TypeError, ValueError):
        return 60


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


def cliente_tem_falta_ativa(con, cliente_id):
    """Falta ativa quando a última 'faltou' é posterior à última 'concluída'."""
    row = con.execute(
        """
        SELECT
            MAX(CASE WHEN estado = 'faltou' THEN inicio END) AS ultima_falta,
            MAX(CASE WHEN estado = 'concluída' THEN inicio END) AS ultima_concluida
        FROM marcacoes
        WHERE cliente_id = ?
        """,
        (cliente_id,),
    ).fetchone()

    if not row or not row["ultima_falta"]:
        return False

    return (
        not row["ultima_concluida"]
        or row["ultima_falta"] > row["ultima_concluida"]
    )


def obter_clientes_inativos(con, dias=None, apenas_pendentes=False):
    """Clientes inativos; opcionalmente só os alertas ainda não consultados."""
    if dias is None:
        dias = obter_dias_inatividade(con)
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

    # Navegação rápida por meses: mês atual + 5 seguintes
    nomes_meses = [
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez"
    ]

    meses_rapidos = []
    base_mes = date.today().replace(day=1)

    for offset in range(6):
        ano = base_mes.year + ((base_mes.month - 1 + offset) // 12)
        mes = ((base_mes.month - 1 + offset) % 12) + 1
        primeiro_dia = date(ano, mes, 1)

        meses_rapidos.append({
            "nome": nomes_meses[mes - 1],
            "ano": ano,
            "data": primeiro_dia.isoformat(),
            "ativo": (
                inicio_semana.year == ano
                and (
                    inicio_semana.month == mes
                    or fim_semana.month == mes
                )
            ),
        })

    con = get_db()
    concretizar_marcacoes_vencidas(con)
    utilizador = utilizador_atual()
    barbeiros = con.execute(
        "SELECT id, nome FROM utilizadores WHERE ativo = 1 AND papel IN ('gestor', 'barbeiro') ORDER BY nome COLLATE NOCASE"
    ).fetchall()
    barbeiro_pedido = request.args.get("barbeiro", "").strip()
    barbeiro_id = None
    if barbeiro_pedido.isdigit() and any(b["id"] == int(barbeiro_pedido) for b in barbeiros) and pode_consultar_agenda(int(barbeiro_pedido)):
        barbeiro_id = int(barbeiro_pedido)
    elif utilizador["papel"] == "barbeiro":
        barbeiro_id = utilizador["id"]

    filtro_barbeiro = " AND m.barbeiro_id = ?" if barbeiro_id else ""
    marcacoes = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.servico, m.estado, c.nome, m.barbeiro_id
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) BETWEEN ? AND ? AND m.estado != 'cancelada'""" + filtro_barbeiro + " ORDER BY m.inicio",
        (inicio_semana.isoformat(), fim_semana.isoformat(), *([barbeiro_id] if barbeiro_id else [])),
    ).fetchall()
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
                "hora_fim": (inicio_m + timedelta(minutes=m["duracao_minutos"])).strftime("%H:%M"),
                "hora_base": hora_base.strftime("%H:%M"),
                "deslocamento": deslocamento,
                "duracao": m["duracao_minutos"],
                "servico": m["servico"],
                "estado": m["estado"],
                "nome": m["nome"] if gestor() or m["barbeiro_id"] == utilizador["id"] else "Ocupado",
                "barbeiro_id": m["barbeiro_id"],
            })
        # Calcula, para cada marcação, os intervalos em que existe
        # sobreposição com outra marcação do mesmo dia.
        for atual in marcacoes_dia:
            atual_inicio = datetime.fromisoformat(atual["inicio"])
            atual_fim = atual_inicio + timedelta(minutes=atual["duracao"])
            faixas = []

            for outra in marcacoes_dia:
                if outra["id"] == atual["id"]:
                    continue

                # Marcações canceladas não contam como conflito operacional.
                if atual["estado"] == "cancelada" or outra["estado"] == "cancelada":
                    continue

                outra_inicio = datetime.fromisoformat(outra["inicio"])
                outra_fim = outra_inicio + timedelta(minutes=outra["duracao"])

                conflito_inicio = max(atual_inicio, outra_inicio)
                conflito_fim = min(atual_fim, outra_fim)

                if conflito_inicio < conflito_fim:
                    inicio_minutos = int(
                        (conflito_inicio - atual_inicio).total_seconds() // 60
                    )
                    duracao_minutos = int(
                        (conflito_fim - conflito_inicio).total_seconds() // 60
                    )

                    faixa = {
                        "inicio": inicio_minutos,
                        "duracao": duracao_minutos,
                    }

                    if faixa not in faixas:
                        faixas.append(faixa)

            atual["sobreposicoes"] = faixas

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
        meses_rapidos=meses_rapidos,
        utilizador=utilizador,
        barbeiros=barbeiros,
        barbeiro_selecionado=barbeiro_id,
        pode_consultar_outros=bool(utilizador["pode_consultar_agendas"]),
        pode_marcar_outros=bool(utilizador["pode_marcar_outros"]),
    )

@app.route("/servicos")
def servicos():
    servicos_lista = [
        {"nome": "Corte"},
        {"nome": "Barba"},
        {"nome": "Corte + Barba"},
    ]
    return render_template("servicos.html", servicos=servicos_lista)


@app.route("/produtos")
def produtos():
    produtos_lista = [
        {
            "nome": "Gel de cabelo",
            "descricao": "Gel de fixação para styling diário.",
            "preco": "8,00 €",
            "imagem": "produto-gel-demo.svg",
            "demo": True,
        }
    ]
    return render_template("produtos.html", produtos=produtos_lista)


@app.route("/definicoes", methods=["GET", "POST"])
def definicoes():
    con = get_db()

    if request.method == "POST":
        try:
            dias = int(request.form.get("dias_inatividade", "60"))
        except ValueError:
            dias = 60

        if dias < 15:
            dias = 15
        elif dias > 365:
            dias = 365

        con.execute("""
            INSERT INTO definicoes (chave, valor)
            VALUES ('dias_inatividade', ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
        """, (str(dias),))
        con.commit()
        con.close()
        return redirect(url_for("definicoes", salvo="1"))

    dias = obter_dias_inatividade(con)
    con.close()

    return render_template(
        "definicoes.html",
        dias_inatividade=dias,
        salvo=request.args.get("salvo") == "1",
    )


@app.route("/clientes")
def clientes():
    pesquisa = request.args.get("q", "").strip()
    apenas_inativos = request.args.get("inativos") == "1"

    top_raw = request.args.get("top", "").strip()
    top_limite = int(top_raw) if top_raw in {"10", "50", "100"} else None

    termo = f"%{pesquisa}%"
    con = get_db()

    total_clientes = con.execute(
        "SELECT COUNT(*) FROM clientes"
    ).fetchone()[0]

    dias_inatividade = obter_dias_inatividade(con)
    limite_inatividade = (
        datetime.now() - timedelta(days=dias_inatividade)
    ).strftime("%Y-%m-%dT%H:%M")

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
        LEFT JOIN telefones tp
            ON tp.cliente_id = c.id AND tp.atual = 1
        LEFT JOIN marcacoes m
            ON m.cliente_id = c.id
        WHERE (? = ''
           OR c.nome LIKE ? COLLATE NOCASE
           OR COALESCE(c.email, '') LIKE ? COLLATE NOCASE
           OR COALESCE(tp.numero, '') LIKE ?
           OR COALESCE(tp.numero_normalizado, '') LIKE ?)
        GROUP BY c.id
        HAVING (? = 0 OR (ultimo_corte IS NOT NULL AND ultimo_corte <= ?))
           AND (? IS NULL OR SUM(CASE WHEN m.estado = 'concluída' THEN 1 ELSE 0 END) > 0)
        ORDER BY
            CASE WHEN ? IS NOT NULL
                 THEN SUM(CASE WHEN m.estado = 'concluída' THEN 1 ELSE 0 END)
            END DESC,
            CASE WHEN ? IS NOT NULL THEN ultimo_corte END DESC,
            c.nome COLLATE NOCASE
        LIMIT COALESCE(?, -1)
    """, (
        pesquisa, termo, termo, termo, termo,
        1 if apenas_inativos else 0, limite_inatividade,
        top_limite,
        top_limite,
        top_limite,
        top_limite,
    )).fetchall()

    total_inativos = len(obter_clientes_inativos(con))

    clientes_falta_ativa = {
        cliente["id"]
        for cliente in clientes_lista
        if cliente_tem_falta_ativa(con, cliente["id"])
    }

    con.close()

    return render_template(
        "clientes.html",
        clientes=clientes_lista,
        clientes_falta_ativa=clientes_falta_ativa,
        pesquisa=pesquisa,
        apenas_inativos=apenas_inativos,
        top10=(top_limite == 10),
        top_limite=top_limite,
        total_clientes=total_clientes,
        total_inativos=total_inativos,
    )


@app.route("/clientes/novo", methods=["GET", "POST"])
def novo_cliente():
    if request.method == "GET":
        return render_template("cliente_novo.html")

    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip()

    try:
        data_nascimento = normalizar_data_nascimento(
            request.form.get("data_nascimento", "")
        )
    except ValueError:
        return render_template(
            "cliente_novo.html",
            erro="A data de nascimento não é válida.",
            dados=request.form,
        ), 400

    if not nome or not telefone:
        return render_template(
            "cliente_novo.html",
            erro="Nome e telefone são obrigatórios.",
            dados=request.form,
        ), 400

    numero_normalizado = normalizar_telefone(telefone)
    if not numero_normalizado:
        return render_template(
            "cliente_novo.html",
            erro="Número de telefone inválido.",
            dados=request.form,
        ), 400

    con = get_db()
    cur = con.cursor()

    existente = cur.execute("""
        SELECT c.id
        FROM telefones t
        JOIN clientes c ON c.id = t.cliente_id
        WHERE t.numero_normalizado = ? AND t.atual = 1
        ORDER BY t.id DESC
        LIMIT 1
    """, (numero_normalizado,)).fetchone()

    if existente:
        cliente_id = existente["id"]
        con.close()
        return redirect(f"/clientes/{cliente_id}")

    try:
        cur.execute("""
            INSERT INTO clientes (nome, email, data_nascimento)
            VALUES (?, ?, ?)
        """, (nome, email or None, data_nascimento))

        cliente_id = cur.lastrowid

        cur.execute("""
            INSERT INTO telefones (cliente_id, numero, numero_normalizado)
            VALUES (?, ?, ?)
        """, (cliente_id, telefone, numero_normalizado))

        con.commit()

    except Exception:
        con.rollback()
        con.close()
        raise

    con.close()
    return redirect(f"/clientes/{cliente_id}")

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

    dias_inatividade = obter_dias_inatividade(con)
    limite_inatividade = (datetime.now() - timedelta(days=dias_inatividade)).strftime("%Y-%m-%dT%H:%M")
    if ultimo_corte and ultimo_corte <= limite_inatividade:
        con.execute("""
            UPDATE clientes
            SET alerta_inatividade_visto_em = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (cliente_id,))
        con.commit()

    falta_ativa = cliente_tem_falta_ativa(con, cliente_id)

    con.close()
    return render_template(
        "cliente.html",
        cliente=cliente,
        historico=historico,
        falta_ativa=falta_ativa,
    )


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
    if not cliente:
        con.close()
        return {"ok": True, "encontrado": False}

    ultimas_visitas = con.execute("""
        SELECT inicio, estado
        FROM marcacoes
        WHERE cliente_id = ?
        ORDER BY inicio DESC
        LIMIT 3
    """, (cliente["id"],)).fetchall()

    con.close()

    return {
        "ok": True,
        "encontrado": True,
        "cliente": {
            "id": cliente["id"],
            "nome": cliente["nome"],
            "telefone": cliente["numero"],
            "email": cliente["email"] or "",
            "data_nascimento": cliente["data_nascimento"] or "",
            "ultimas_visitas": [
                {
                    "inicio": visita["inicio"],
                    "estado": visita["estado"],
                }
                for visita in ultimas_visitas
            ],
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

    utilizador = utilizador_atual()
    barbeiro_id = request.args.get("barbeiro_id", type=int)
    if not barbeiro_id:
        barbeiro_id = utilizador["id"]
    if not pode_consultar_agenda(barbeiro_id):
        return {"ok": False, "erro": "Barbeiro inválido"}, 403

    fim = inicio + timedelta(minutes=duracao)
    con = get_db()
    concretizar_marcacoes_vencidas(con)
    marcacoes = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.servico, c.nome
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) = ? AND m.estado != 'cancelada' AND m.barbeiro_id = ?
        ORDER BY m.inicio
    """, (inicio.date().isoformat(), barbeiro_id)).fetchall()
    con.close()

    conflitos = []
    for m in marcacoes:
        existente_inicio = datetime.fromisoformat(m["inicio"])
        existente_fim = existente_inicio + timedelta(minutes=m["duracao_minutos"])
        if inicio < existente_fim and fim > existente_inicio:
            conflitos.append({"id": m["id"], "nome": m["nome"] if barbeiro_permitido(barbeiro_id) else "Ocupado", "servico": m["servico"] if barbeiro_permitido(barbeiro_id) else "", "inicio": existente_inicio.strftime("%H:%M"), "fim": existente_fim.strftime("%H:%M")})

    return {"ok": True, "disponivel": len(conflitos) == 0, "data": inicio.date().isoformat(), "inicio": inicio.strftime("%H:%M"), "fim": fim.strftime("%H:%M"), "duracao": duracao, "conflitos": conflitos}


@app.route("/marcacoes/nova", methods=["POST"])
def nova_marcacao():
    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip()

    try:
        data_nascimento = normalizar_data_nascimento(
            request.form.get("data_nascimento", "")
        )
    except ValueError:
        return "Data de nascimento inválida", 400

    observacoes = request.form.get("observacoes", "").strip() or None
    utilizador = utilizador_atual()
    barbeiro_id = request.form.get("barbeiro_id", type=int)
    if not barbeiro_id:
        barbeiro_id = utilizador["id"]
    if not pode_marcar_para(barbeiro_id):
        return "Barbeiro inválido", 403
    inicio = request.form.get("inicio", "").strip()
    servico = ""
    try:
        duracao = int(request.form.get("duracao", 30))
        novo_inicio = datetime.fromisoformat(inicio)
    except (ValueError, TypeError):
        return "Data, hora ou duração inválida", 400

    if not nome or not telefone or not inicio or duracao not in (15, 30, 45, 60, 90):
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
        WHERE substr(m.inicio, 1, 10) = ? AND m.estado != 'cancelada' AND m.barbeiro_id = ?
    """, (novo_inicio.date().isoformat(), barbeiro_id)).fetchall()

    for m in conflitos:
        existente_inicio = datetime.fromisoformat(m["inicio"])
        existente_fim = existente_inicio + timedelta(minutes=m["duracao_minutos"])
        if novo_inicio < existente_fim and novo_fim > existente_inicio:
            con.close()
            return "Horário ocupado", 409

    try:
        cur = con.cursor()
        cliente = cur.execute("""
            SELECT c.id, t.id AS telefone_id
            FROM telefones t
            JOIN clientes c ON c.id = t.cliente_id
            WHERE t.numero_normalizado = ? AND t.atual = 1
            ORDER BY t.id DESC
            LIMIT 1
        """, (numero_normalizado,)).fetchone()

        if cliente:
            cliente_id = cliente["id"]
            telefone_id = cliente["telefone_id"]
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
            telefone_id = cur.lastrowid

        cur.execute("""
            INSERT INTO marcacoes
            (cliente_id, inicio, duracao_minutos, servico, observacoes, barbeiro_id, criado_por_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (cliente_id, inicio, duracao, servico, observacoes, barbeiro_id, utilizador["id"]))
        marcacao_id = cur.lastrowid

        # Lembrete por SMS às 18:00 do dia anterior.
        # Só é criado se essa hora ainda estiver no futuro.
        previsto_para = datetime.combine(
            novo_inicio.date() - timedelta(days=1),
            datetime.strptime("18:00", "%H:%M").time()
        )

        if previsto_para > datetime.now():
            data_formatada = novo_inicio.strftime("%d/%m/%Y")
            hora_formatada = novo_inicio.strftime("%H:%M")

            mensagem_lembrete = (
                f"Blessed Barbearia: Ola {nome}, lembramos que tem uma marcacao amanha. "
                f"Data: {data_formatada}. Hora: {hora_formatada}."
            )

            cur.execute("""
                INSERT OR IGNORE INTO sms_fila
                (cliente_id, telefone_id, marcacao_id, telefone_destino, tipo,
                 mensagem, previsto_para, idempotency_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cliente_id,
                telefone_id,
                marcacao_id,
                telefone,
                "lembrete_dia_anterior",
                mensagem_lembrete,
                previsto_para.isoformat(timespec="seconds"),
                f"lembrete_dia_anterior:{marcacao_id}",
            ))

        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    data_formatada = novo_inicio.strftime("%d/%m/%Y")
    hora_formatada = novo_inicio.strftime("%H:%M")

    texto_sms = (
        f"Blessed Barbearia: Ola {nome}, a sua marcacao esta confirmada. "
        f"Data: {data_formatada}. Hora: {hora_formatada}."
    )

    enviar_sms_smsgate(telefone, texto_sms)

    return redirect(url_for("semana", data=novo_inicio.date().isoformat()))

@app.route("/marcacoes/<int:marcacao_id>/duracao", methods=["POST"])
def alterar_duracao_marcacao(marcacao_id):
    try:
        duracao = int(request.form.get("duracao", 0))
    except (ValueError, TypeError):
        return {"ok": False, "erro": "Duração inválida"}, 400

    if duracao not in (15, 30, 45, 60, 90):
        return {"ok": False, "erro": "Duração inválida"}, 400

    forcar = request.form.get("forcar", "") == "1"

    con = get_db()
    concretizar_marcacoes_vencidas(con)

    marcacao = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.estado, m.barbeiro_id, m.criado_por_id
        FROM marcacoes m
        WHERE m.id = ?
    """, (marcacao_id,)).fetchone()

    if not marcacao:
        con.close()
        return {"ok": False, "erro": "Marcação não encontrada"}, 404
    if not pode_alterar_marcacao(marcacao):
        con.close()
        return {"ok": False, "erro": "Sem permissão para esta marcação"}, 403

    novo_inicio = datetime.fromisoformat(marcacao["inicio"])
    novo_fim = novo_inicio + timedelta(minutes=duracao)

    conflitos_db = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, c.nome
        FROM marcacoes m
        JOIN clientes c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) = ?
          AND m.id != ?
          AND m.estado != 'cancelada'
        ORDER BY m.inicio
    """, (novo_inicio.date().isoformat(), marcacao_id)).fetchall()

    conflitos = []

    for outra in conflitos_db:
        outra_inicio = datetime.fromisoformat(outra["inicio"])
        outra_fim = outra_inicio + timedelta(minutes=outra["duracao_minutos"])

        if novo_inicio < outra_fim and novo_fim > outra_inicio:
            sobreposicao_inicio = max(novo_inicio, outra_inicio)
            sobreposicao_fim = min(novo_fim, outra_fim)
            minutos = int(
                (sobreposicao_fim - sobreposicao_inicio).total_seconds() // 60
            )

            conflitos.append({
                "id": outra["id"],
                "nome": outra["nome"],
                "inicio": outra_inicio.strftime("%H:%M"),
                "fim": outra_fim.strftime("%H:%M"),
                "sobreposicao_minutos": minutos,
            })

    if conflitos and not forcar:
        con.close()
        return {
            "ok": False,
            "requer_confirmacao": True,
            "duracao": duracao,
            "conflitos": conflitos,
        }, 409

    con.execute("""
        UPDATE marcacoes
        SET duracao_minutos = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (duracao, marcacao_id))

    con.commit()
    con.close()

    return {
        "ok": True,
        "duracao": duracao,
        "forcado": bool(conflitos and forcar),
    }

@app.route("/marcacoes/<int:marcacao_id>/estado", methods=["POST"])
def alterar_estado_marcacao(marcacao_id):
    estado = request.form.get("estado", "").strip()
    estados_validos = {"marcada", "concluída", "cancelada", "faltou"}
    if estado not in estados_validos:
        return "Estado inválido", 400

    con = get_db()
    concretizar_marcacoes_vencidas(con)
    marcacao = con.execute("SELECT id, inicio, barbeiro_id, criado_por_id FROM marcacoes WHERE id = ?", (marcacao_id,)).fetchone()
    if not marcacao:
        con.close()
        return "Marcação não encontrada", 404
    if not pode_alterar_marcacao(marcacao):
        con.close()
        return "Sem permissão para esta marcação", 403

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
