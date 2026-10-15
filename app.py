import base64
import shutil
import csv
import io
import json
import os
import secrets
import threading
import sqlite3
import urllib.error
import urllib.request
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from contextlib import closing

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("BLESSED_SECRET_KEY", "blessed-multiuser-test-only")

DB = Path(os.environ.get("BLESSED_DB", str(Path(__file__).with_name("blessed.db")))).expanduser()
FUSO_BARBEARIA = ZoneInfo(os.environ.get("BLESSED_TIMEZONE", "Europe/Lisbon"))


def agora_barbearia():
    return datetime.now(FUSO_BARBEARIA)


def semana_por_defeito(agora):
    """Sexta às 22h e fim de semana abrem a próxima semana de trabalho."""
    hoje = agora.date()
    segunda = hoje - timedelta(days=hoje.weekday())
    if hoje.weekday() > 4 or (hoje.weekday() == 4 and agora.hour >= 22):
        segunda += timedelta(days=7)
    return segunda

LOG_EMAIL_DESTINO = "pajogusi.uk@gmail.com"
LOG_LOTE_TAMANHO = 10
LOG_LOCK = threading.Lock()
EQUIPAMENTO_COOKIE = "blessed_multiuser_equipamento"



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
            "name": os.environ.get(
                "BREVO_SENDER_NAME",
                "Blessed Barbearia"
            ).strip(),
            "email": os.environ.get(
                "BREVO_SENDER_EMAIL",
                "pjgs.form@gmail.com"
            ).strip(),
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
    if app.config.get("TESTING") or os.environ.get("BLESSED_DISABLE_SMS") == "1":
        print("SMS TESTE: envio real bloqueado")
        return True

    telefone = normalizar_telefone(telefone)
    texto = (texto or "").strip()

    if not telefone or not texto:
        return False

    # Each establishment explicitly selects its own SMS gateway and credentials.
    # Never fall back to Bruno's shared gateway or credentials.
    sms_env = os.environ.get("BLESSED_SMSGATE_ENV", "").strip()
    sms_url = os.environ.get("BLESSED_SMSGATE_URL", "").strip()
    if not sms_env or not sms_url:
        print("SMS: gateway e credenciais do estabelecimento não configurados")
        return False
    if not sms_url.startswith(("https://", "http://")):
        print("SMS: endereço do gateway inválido")
        return False
    env_path = Path(sms_env).expanduser()
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
        sms_url,
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


def enviar_sms_smsto(telefone, texto):
    # Envia SMS através da SMS.to. Devolve True/False.

    if app.config.get("TESTING"):
        print("SMS.to TESTE: envio real bloqueado")
        return True

    if os.environ.get("BLESSED_DISABLE_SMS") == "1":
        print("SMS.to: envio real bloqueado por BLESSED_DISABLE_SMS")
        return False

    telefone = normalizar_telefone(telefone)
    texto = (texto or "").strip()

    if not telefone or not texto:
        return False

    api_key = os.environ.get("SMSTO_API_KEY", "").strip()
    if not api_key:
        print("SMS.to: SMSTO_API_KEY não configurada")
        return False

    payload = {
        "message": texto,
        "to": telefone,
        "sender_id": "BLESSED",
    }

    req = urllib.request.Request(
        "https://api.sms.to/sms/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resposta:
            corpo = resposta.read().decode("utf-8", errors="replace")

            if not (200 <= resposta.status < 300):
                print(f"SMS.to: resposta HTTP {resposta.status}")
                return False

            try:
                dados = json.loads(corpo)
            except json.JSONDecodeError:
                print("SMS.to: resposta inválida da API")
                return False

            if dados.get("success") is True:
                message_id = (
                    dados.get("message_id")
                    or dados.get("id")
                    or dados.get("messageId")
                )

                if message_id:
                    print(f"SMS.to: mensagem aceite pela API | message_id={message_id}")
                else:
                    print("SMS.to: mensagem aceite pela API | message_id não devolvido")
                    print("SMS.to: resposta:", dados)

                return True

            print(
                "SMS.to: API recusou a mensagem: "
                + str(dados.get("message", "erro desconhecido"))
            )
            return False

    except urllib.error.HTTPError as erro:
        print(f"SMS.to: erro HTTP {erro.code}")
        return False

    except (urllib.error.URLError, TimeoutError) as erro:
        print(f"SMS.to: falha de ligação: {erro}")
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
                """
                SELECT
                    id,
                    nome,
                    username,
                    avatar_path,
                    papel,
                    ativo,
                    pode_consultar_agendas,
                    pode_marcar_outros,
                    sms_autorizado,
                    sms_provider,
                    e_admin
                FROM utilizadores
                WHERE id = ?
                """,
                (utilizador_id,),
            ).fetchone()
            con.close()

    return g.utilizador

def gestor():
    utilizador = utilizador_atual()
    return bool(utilizador and (utilizador["papel"] == "gestor" or utilizador["e_admin"]))


def requer_login(func):
    @wraps(func)
    def protegido(*args, **kwargs):
        utilizador = utilizador_atual()
        if not utilizador or not utilizador["ativo"]:
            session.clear()
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return protegido


def admin_atual():
    utilizador = utilizador_atual()
    return bool(utilizador and utilizador["e_admin"])


def requer_admin(func):
    @wraps(func)
    @requer_login
    def protegido(*args, **kwargs):
        if not admin_atual():
            abort(403)
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


def renderizar_modelo_comunicacao(con, chave, **dados):
    """Lê um modelo ativo da BD e substitui as variáveis conhecidas."""
    modelo = con.execute("""
        SELECT chave, canal, nome, assunto, conteudo, ativo
        FROM modelos_comunicacao
        WHERE chave = ?
        LIMIT 1
    """, (chave,)).fetchone()

    if not modelo or not modelo["ativo"]:
        return None

    assunto = modelo["assunto"] or ""
    conteudo = modelo["conteudo"] or ""

    for campo, valor in dados.items():
        marcador = "{" + campo + "}"
        valor = "" if valor is None else str(valor)
        assunto = assunto.replace(marcador, valor)
        conteudo = conteudo.replace(marcador, valor)

    return {
        "assunto": assunto,
        "conteudo": conteudo,
    }


def obter_email_barbeiro(con, barbeiro_id):
    """Configuração de email do profissional."""
    return con.execute("""
        SELECT
            id,
            nome,
            username,
            email_ativo,
            email_confirmacao,
            email_lembrete_24h,
            email_lembrete_1h
        FROM utilizadores
        WHERE id = ?
          AND ativo = 1
    """, (barbeiro_id,)).fetchone()


def email_barbeiro_permitido(config):
    return bool(
        config
        and config["email_ativo"]
    )


def obter_sms_barbeiro(con, barbeiro_id):
    """Configuração SMS do profissional. Sem autorização não existe envio."""
    return con.execute("""
        SELECT id, nome, username, sms_autorizado, sms_provider
        FROM utilizadores
        WHERE id = ? AND ativo = 1
    """, (barbeiro_id,)).fetchone()


def sms_barbeiro_permitido(config):
    return bool(
        config
        and config["sms_autorizado"]
        and config["sms_provider"]
    )


def enviar_sms_do_barbeiro(barbeiro_id, telefone, texto):
    """Encaminha SMS pelo fornecedor pertencente ao respetivo profissional."""
    con = get_db()
    config = obter_sms_barbeiro(con, barbeiro_id)
    con.close()

    if not sms_barbeiro_permitido(config):
        print(f"SMS: bloqueado para barbeiro_id={barbeiro_id}")
        return False

    if config["sms_provider"] == "smsto":
        return enviar_sms_smsto(telefone, texto)

    if config["sms_provider"] == "smsgate":
        return enviar_sms_smsgate(telefone, texto)

    print(
        f"SMS: fornecedor '{config['sms_provider']}' "
        f"ainda não implementado para barbeiro_id={barbeiro_id}"
    )
    return False


def pode_gerir_cliente(cliente):
    return bool(utilizador_atual() and cliente)


def barbeiro_permitido(barbeiro_id):
    """O gestor pode escolher qualquer profissional; o barbeiro apenas a si próprio."""
    utilizador = utilizador_atual()
    return bool(utilizador and (utilizador["papel"] == "gestor" or utilizador["id"] == barbeiro_id))


def pode_consultar_agenda(barbeiro_id):
    # Todos os utilizadores autenticados podem consultar agendas individuais.
    return bool(utilizador_atual() and barbeiro_id)


def pode_marcar_para(barbeiro_id):
    """Gestor pode marcar qualquer profissional; barbeiro normal apenas a si próprio."""
    utilizador = utilizador_atual()
    return bool(utilizador and barbeiro_id and (
        utilizador["papel"] == "gestor"
        or utilizador["e_admin"]
        or utilizador["id"] == barbeiro_id
    ))


def agenda_aberta_id():
    try:
        return int(session.get("agenda_aberta_id"))
    except (TypeError, ValueError):
        return None


def pode_alterar_marcacao(marcacao):
    """Admin, gestor, barbeiro responsável ou quem a criou para outro pode alterar."""
    utilizador = utilizador_atual()
    return bool(utilizador and (
        utilizador["e_admin"]
        or utilizador["papel"] == "gestor"
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
    fim = inicio + timedelta(minutes=duracao_minutos)
    if conflitos_indisponibilidade(con, barbeiro_id, inicio, fim):
        return False
    marcacoes = con.execute("""
        SELECT inicio, duracao_minutos FROM marcacoes
        WHERE barbeiro_id = ? AND estado != 'cancelada'
          AND substr(inicio, 1, 10) = ?
        UNION ALL
        SELECT inicio, duracao_minutos FROM reservas_online
        WHERE barbeiro_id = ? AND estado = 'aguarda_pagamento' AND expira_em > ?
          AND substr(inicio, 1, 10) = ?
    """, (barbeiro_id, inicio.date().isoformat(), barbeiro_id, datetime.now().astimezone().isoformat(timespec="seconds"), inicio.date().isoformat())).fetchall()
    for item in marcacoes:
        existente_inicio = datetime.fromisoformat(item["inicio"])
        existente_fim = existente_inicio + timedelta(minutes=item["duracao_minutos"])
        if inicio < existente_fim and fim > existente_inicio:
            return False
    return True


def conflitos_indisponibilidade(con, barbeiro_id, inicio, fim, ignorar_bloqueio_id=None):
    """Encerramentos globais, ausências e compromissos do profissional."""
    periodos = list(con.execute("""
        SELECT id, tipo, inicio, fim, motivo, barbeiro_id
        FROM indisponibilidades
        WHERE inicio < ? AND fim > ?
          AND (tipo = 'encerramento' OR barbeiro_id = ?)
        ORDER BY inicio
    """, (fim.isoformat(timespec="minutes"), inicio.isoformat(timespec="minutes"), barbeiro_id)).fetchall())

    for item in con.execute("SELECT * FROM bloqueios_pessoais WHERE barbeiro_id = ? AND (? IS NULL OR id != ?)",
                            (barbeiro_id, ignorar_bloqueio_id, ignorar_bloqueio_id)).fetchall():
        item_inicio = datetime.fromisoformat(item["inicio"])
        item_fim = item_inicio + timedelta(minutes=item["duracao_minutos"])
        if inicio < item_fim and fim > item_inicio:
            periodos.append(dict(id=item["id"], tipo="pessoal", inicio=item["inicio"],
                fim=item_fim.isoformat(timespec="minutes"), motivo=item["descricao"], barbeiro_id=barbeiro_id))
    return periodos


def pode_gerir_indisponibilidade(item):
    utilizador = utilizador_atual()
    return bool(utilizador and (gestor() or (
        item["tipo"] == "ausencia" and item["barbeiro_id"] == utilizador["id"]
    )))


@app.before_request
def reconhecer_equipamento():
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return
    g.equipamento = None
    g.equipamento_novo = False
    utilizador = utilizador_atual()
    g.ator_log = dict(utilizador) if utilizador and utilizador["ativo"] else None
    if not g.ator_log and request.endpoint not in {"login", "logout"}:
        return
    try:
        with closing(get_db()) as con, con:
            codigo = request.cookies.get(EQUIPAMENTO_COOKIE, "")
            row = None
            if len(codigo) == 32 and all(c in "0123456789abcdef" for c in codigo):
                row = con.execute("SELECT * FROM equipamentos WHERE id = ?", (codigo,)).fetchone()
            if row is None:
                codigo = secrets.token_hex(16)
                con.execute("""
                    INSERT INTO equipamentos (id, nome, csrf_token, criado_em)
                    VALUES (?, '', ?, ?)
                """, (codigo, secrets.token_urlsafe(32), agora_barbearia().isoformat(timespec="seconds")))
                row = con.execute("SELECT * FROM equipamentos WHERE id = ?", (codigo,)).fetchone()
                g.equipamento_novo = True
            g.equipamento = dict(row)
    except sqlite3.Error as erro:
        print(f"EQUIPAMENTO: falha na identificação: {erro}")


@app.before_request
def exigir_autenticacao():
    if request.endpoint in {
        "login",
        "logout",
        "online_reservar",
        "online_reservar_submeter",
        "online_reserva_pagamento",
        "static",
        "blessed_service_worker",
    }:
        return None

    utilizador = utilizador_atual()

    if not utilizador or not utilizador["ativo"]:
        session.clear()
        return redirect(url_for("login"))

    # Bruno/gestor tem acesso total.
    if utilizador["papel"] == "gestor" or utilizador["e_admin"]:
        return None

    # Barbeiros normais só podem usar a sua própria agenda
    # e as ações necessárias para trabalhar nela.
    permitidos_barbeiro = {
        "entrada",
        "home",
        "blessed_service_worker",
        "semana",
        "estatisticas",
        "contabilidade",
        "cliente_detalhe",
        "novo_cliente",
        "clientes",
        "cliente_por_telefone",
        "clientes_por_nome",
        "clientes_sincronizacao_offline",
        "cliente_para_marcacao",
        "equipamento",
        "nomear_equipamento",
        "disponibilidade",
        "nova_marcacao",
        "sincronizar_marcacao_offline",
        "alterar_duracao_marcacao",
        "alterar_estado_marcacao",
        "fechar_marcacao",
        "cancelar_serie_futura",
        "nova_indisponibilidade",
        "eliminar_indisponibilidade",
        "novo_bloqueio_pessoal",
        "editar_bloqueio_pessoal",
        "eliminar_bloqueio_pessoal",
    }

    if request.endpoint not in permitidos_barbeiro:
        return redirect(url_for("semana"))

    return None


@app.route("/blessed-sw.js")
def blessed_service_worker():
    resposta = app.send_static_file("blessed-sw.js")
    resposta.headers["Service-Worker-Allowed"] = "/"
    resposta.headers["Cache-Control"] = "no-cache"
    return resposta


@app.route("/equipamento")
def equipamento():
    return render_template("equipamento.html", equipamento=getattr(g, "equipamento", None),
                           salvo=request.args.get("salvo") == "1")


@app.route("/equipamento/nome", methods=["POST"])
def nomear_equipamento():
    equipamento = getattr(g, "equipamento", None)
    if not equipamento:
        return "Não foi possível identificar este navegador. Atualiza a página.", 503
    if not secrets.compare_digest(request.form.get("csrf_token", "").encode(), equipamento["csrf_token"].encode()):
        return "Formulário expirado. Volta à página Equipamento.", 403
    nome_original = request.form.get("nome", "")
    nome = " ".join(nome_original.split())
    if not nome or len(nome) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in nome_original):
        return "Indica um nome entre 1 e 80 caracteres.", 400
    with closing(get_db()) as con, con:
        con.execute("UPDATE equipamentos SET nome = ? WHERE id = ?", (nome, equipamento["id"]))
    g.equipamento["nome"] = nome
    return redirect(url_for("equipamento", salvo="1"))


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
        "SELECT id, nome FROM utilizadores WHERE ativo = 1 AND COALESCE(e_admin,0) = 0 ORDER BY nome COLLATE NOCASE"
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
        if inicio.tzinfo is not None:
            raise ValueError
        duracao = int(request.form.get("duracao", "30"))
    except (TypeError, ValueError):
        return render_template("reservar_online.html", erro="Escolhe uma data e hora válidas."), 400
    if not nome or not telefone or servico not in {"Corte", "Barba", "Corte + Barba"} or duracao not in {15, 30, 45, 60, 90}:
        return render_template("reservar_online.html", erro="Preenche os dados obrigatórios."), 400

    con = get_db()
    expirar_reservas_online(con)
    con.execute("BEGIN IMMEDIATE")
    barbeiros = con.execute("SELECT id, nome FROM utilizadores WHERE ativo = 1 AND COALESCE(e_admin,0) = 0 ORDER BY nome COLLATE NOCASE").fetchall()
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



def identificar_dispositivo(user_agent):
    ua = (user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "Tablet"
    if "iphone" in ua:
        return "Telemóvel (iPhone)"
    if "android" in ua:
        return "Telemóvel (Android)" if "mobile" in ua else "Tablet (Android)"
    if "windows" in ua:
        return "Computador (Windows)"
    if "linux" in ua:
        return "Computador (Linux)"
    if "macintosh" in ua or "mac os" in ua:
        return "Computador (Mac)"
    return "Dispositivo desconhecido"


def _enviar_logs_email(rows, descricao):
    if not rows:
        return False
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ID", "Data/Hora", "Metodo", "Caminho", "HTTP", "IP", "Utilizador ID",
                     "Utilizador", "Username", "Equipamento ID", "Equipamento", "Novo equipamento",
                     "Dispositivo", "User-Agent", "Acao", "Agenda ID", "Agenda", "Marcacao ID"])
    def celula(valor):
        valor = "" if valor is None else str(valor)
        return "'" + valor if valor.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else valor
    for row in rows:
        writer.writerow([celula(row[chave]) for chave in (
            "id", "criado_em", "metodo", "caminho", "estado_http", "ip", "utilizador_id",
            "utilizador_nome", "utilizador_username", "equipamento_id", "equipamento_nome",
            "equipamento_novo", "dispositivo", "user_agent", "acao", "alvo_barbeiro_id",
            "alvo_barbeiro_nome", "marcacao_id")])
    agora = datetime.now().astimezone()
    nome = agora.strftime("blessed-atividades-%Y%m%d-%H%M%S.csv")
    return enviar_email_brevo(
        LOG_EMAIL_DESTINO,
        f"Blessed — logs de atividade ({descricao})",
        f"Segue em anexo o relatório de atividade: {descricao}.",
        anexo_nome=nome,
        anexo_conteudo=buffer.getvalue().encode("utf-8-sig"),
    )


@app.after_request
def registar_atividade_site(response):
    equipamento = getattr(g, "equipamento", None)
    if equipamento:
        response.set_cookie(EQUIPAMENTO_COOKIE, equipamento["id"], max_age=365 * 24 * 60 * 60,
                            httponly=True, samesite="Lax", path="/",
                            secure=request.is_secure or request.headers.get("X-Forwarded-Proto") == "https")
    # A bateria automática nunca gera logs nem emails reais.
    if app.config.get("TESTING"):
        return response

    # Recursos estáticos não contam como atividade do utilizador.
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return response

    try:
        with LOG_LOCK:
            with closing(get_db()) as con, con:
                ator = getattr(g, "ator_log", None)
                if request.endpoint == "login" and session.get("utilizador_id"):
                    ator = con.execute("SELECT id, nome, username FROM utilizadores WHERE id = ?",
                                       (session["utilizador_id"],)).fetchone()
                ip = (request.headers.get("CF-Connecting-IP")
                      or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                      or request.remote_addr or "")
                equipamento = equipamento or {}
                user_agent = request.headers.get("User-Agent", "")
                extra = getattr(g, "atividade_extra", {}) or {}
                con.execute("""
                    INSERT INTO atividade_log
                        (criado_em, metodo, caminho, estado_http, ip,
                         utilizador_id, utilizador_nome, utilizador_username,
                         equipamento_id, equipamento_nome, equipamento_novo, dispositivo, user_agent,
                         acao, alvo_barbeiro_id, alvo_barbeiro_nome, marcacao_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (agora_barbearia().isoformat(timespec="seconds"), request.method, request.path,
                      int(response.status_code), ip,
                      ator["id"] if ator else None, ator["nome"] if ator else "",
                      ator["username"] if ator else "", equipamento.get("id", ""),
                      equipamento.get("nome", "") or "Por identificar",
                      int(getattr(g, "equipamento_novo", False)), identificar_dispositivo(user_agent), user_agent,
                      extra.get("acao", ""), extra.get("alvo_barbeiro_id"),
                      extra.get("alvo_barbeiro_nome", ""), extra.get("marcacao_id")))
                # O envio por email permanece manual no Admin > Logs.

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

    # ---------------------------------------------------------
    # CAMPANHAS
    #
    # O módulo evoluiu para suportar:
    #   canal: email / sms / ambos
    #   tipo:  ... / livre
    #   estado: ... / confirmada
    #
    # Bases antigas tinham CHECK constraints incompatíveis.
    # SQLite não permite alterar CHECK diretamente, por isso a
    # tabela é reconstruída preservando IDs e dados existentes.
    # ---------------------------------------------------------
    tabela_campanhas = con.execute("""
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'campanhas'
    """).fetchone()

    schema_campanhas_atual = """
        CREATE TABLE campanhas (
            id INTEGER PRIMARY KEY,

            titulo TEXT NOT NULL,
            mensagem TEXT NOT NULL,

            canal TEXT NOT NULL DEFAULT 'email'
                CHECK (canal IN (
                    'email',
                    'sms',
                    'ambos'
                )),

            tipo TEXT NOT NULL DEFAULT 'geral'
                CHECK (tipo IN (
                    'geral',
                    'aniversário',
                    'natal',
                    'ano_novo',
                    'ferias',
                    'horario_especial',
                    'livre'
                )),

            estado TEXT NOT NULL DEFAULT 'rascunho'
                CHECK (estado IN (
                    'rascunho',
                    'confirmada',
                    'agendada',
                    'em_envio',
                    'pausada',
                    'concluida',
                    'cancelada'
                )),

            envio_previsto TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            nome TEXT,
            barbeiro_id INTEGER,
            assunto TEXT,
            total_destinatarios INTEGER NOT NULL DEFAULT 0,
            criado_por_id INTEGER,
            confirmado_em TEXT,

            tamanho_lote INTEGER NOT NULL DEFAULT 10,
            intervalo_segundos INTEGER NOT NULL DEFAULT 60,
            max_por_hora INTEGER NOT NULL DEFAULT 100,
            iniciado_em TEXT,
            pausado_em TEXT,
            concluido_em TEXT
        )
    """

    if tabela_campanhas is None:
        con.execute(schema_campanhas_atual)

    else:
        sql_antigo = tabela_campanhas["sql"] or ""

        precisa_migrar_campanhas = (
            "'ambos'" not in sql_antigo
            or "'livre'" not in sql_antigo
            or "'confirmada'" not in sql_antigo
        )

        if precisa_migrar_campanhas:
            colunas_antigas = {
                row["name"]
                for row in con.execute("PRAGMA table_info(campanhas)")
            }

            colunas_destino = [
                "id",
                "titulo",
                "mensagem",
                "canal",
                "tipo",
                "estado",
                "envio_previsto",
                "criado_em",
                "nome",
                "barbeiro_id",
                "assunto",
                "total_destinatarios",
                "criado_por_id",
                "confirmado_em",
                "tamanho_lote",
                "intervalo_segundos",
                "max_por_hora",
                "iniciado_em",
                "pausado_em",
                "concluido_em",
            ]

            valores_padrao = {
                "nome": "titulo",
                "barbeiro_id": "NULL",
                "assunto": "NULL",
                "total_destinatarios": "0",
                "criado_por_id": "NULL",
                "confirmado_em": "NULL",
                "tamanho_lote": "10",
                "intervalo_segundos": "60",
                "max_por_hora": "100",
                "iniciado_em": "NULL",
                "pausado_em": "NULL",
                "concluido_em": "NULL",
            }

            origem = []

            for coluna in colunas_destino:
                if coluna in colunas_antigas:
                    origem.append(coluna)
                elif coluna in valores_padrao:
                    origem.append(valores_padrao[coluna])
                else:
                    raise RuntimeError(
                        f"Campanhas: coluna obrigatória antiga em falta: {coluna}"
                    )

            # A alteração de foreign_keys só é válida fora de transação.
            con.commit()
            con.execute("PRAGMA foreign_keys = OFF")

            try:
                con.execute("BEGIN IMMEDIATE")

                con.execute(
                    schema_campanhas_atual.replace(
                        "CREATE TABLE campanhas",
                        "CREATE TABLE campanhas_nova",
                        1,
                    )
                )

                con.execute(f"""
                    INSERT INTO campanhas_nova (
                        {", ".join(colunas_destino)}
                    )
                    SELECT
                        {", ".join(origem)}
                    FROM campanhas
                """)

                con.execute("DROP TABLE campanhas")
                con.execute(
                    "ALTER TABLE campanhas_nova RENAME TO campanhas"
                )

                con.commit()

            except Exception:
                con.rollback()
                raise

            finally:
                con.execute("PRAGMA foreign_keys = ON")

            erros_fk = con.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if erros_fk:
                raise RuntimeError(
                    f"Campanhas: foreign_key_check falhou: {erros_fk}"
                )
    colunas = {row["name"] for row in con.execute("PRAGMA table_info(marcacoes)")}
    if "observacoes" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN observacoes TEXT")
    if "serie_id" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN serie_id TEXT")
    if "barbeiro_id" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN barbeiro_id INTEGER")
    if "criado_por_id" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN criado_por_id INTEGER")
    if "valor_cobrado_centimos" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN valor_cobrado_centimos INTEGER")
    if "metodo_pagamento" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN metodo_pagamento TEXT")
    if "fechado_em" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN fechado_em TEXT")
    if "fechado_por_id" not in colunas:
        con.execute("ALTER TABLE marcacoes ADD COLUMN fechado_por_id INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS idx_marcacoes_serie ON marcacoes (serie_id, barbeiro_id, inicio)")

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
    if "sms_autorizado" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN sms_autorizado INTEGER NOT NULL DEFAULT 0")
    if "sms_provider" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN sms_provider TEXT")
    if "e_admin" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN e_admin INTEGER NOT NULL DEFAULT 0")
    if "email_ativo" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN email_ativo INTEGER NOT NULL DEFAULT 0")
    if "email_confirmacao" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN email_confirmacao INTEGER NOT NULL DEFAULT 0")
    if "email_lembrete_24h" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN email_lembrete_24h INTEGER NOT NULL DEFAULT 0")
    if "email_lembrete_1h" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN email_lembrete_1h INTEGER NOT NULL DEFAULT 0")
    if "avatar_path" not in colunas_utilizadores:
        con.execute("ALTER TABLE utilizadores ADD COLUMN avatar_path TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_marcacoes_barbeiro_inicio ON marcacoes (barbeiro_id, inicio)")

    con.execute("""
        CREATE TABLE IF NOT EXISTS indisponibilidades (
            id INTEGER PRIMARY KEY,
            tipo TEXT NOT NULL CHECK (tipo IN ('ausencia', 'encerramento')),
            inicio TEXT NOT NULL,
            fim TEXT NOT NULL CHECK (fim > inicio),
            motivo TEXT NOT NULL,
            barbeiro_id INTEGER,
            criado_por_id INTEGER NOT NULL,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK ((tipo = 'ausencia' AND barbeiro_id IS NOT NULL)
                OR (tipo = 'encerramento' AND barbeiro_id IS NULL)),
            FOREIGN KEY (barbeiro_id) REFERENCES utilizadores(id),
            FOREIGN KEY (criado_por_id) REFERENCES utilizadores(id)
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_indisponibilidades_intervalo ON indisponibilidades (barbeiro_id, inicio, fim)")
    colunas_bloqueios = {
        row["name"]
        for row in con.execute("PRAGMA table_info(bloqueios_pessoais)")
    }
    if colunas_bloqueios and "barbeiro_id" not in colunas_bloqueios:
        total_bloqueios = con.execute(
            "SELECT COUNT(*) FROM bloqueios_pessoais"
        ).fetchone()[0]
        if total_bloqueios:
            raise RuntimeError(
                "bloqueios_pessoais antiga contém dados; migração manual necessária"
            )
        con.execute("DROP TABLE bloqueios_pessoais")

    con.execute("""
        CREATE TABLE IF NOT EXISTS bloqueios_pessoais (
            id INTEGER PRIMARY KEY,
            inicio TEXT NOT NULL,
            duracao_minutos INTEGER NOT NULL CHECK (duracao_minutos BETWEEN 15 AND 240),
            descricao TEXT NOT NULL,
            barbeiro_id INTEGER NOT NULL REFERENCES utilizadores(id),
            criado_por_id INTEGER NOT NULL REFERENCES utilizadores(id),
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_bloqueios_barbeiro_inicio ON bloqueios_pessoais (barbeiro_id, inicio)")


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
    if "barbeiro_id" not in colunas_clientes:
        con.execute("ALTER TABLE clientes ADD COLUMN barbeiro_id INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS idx_clientes_barbeiro ON clientes (barbeiro_id)")

    con.execute("""
        CREATE TABLE IF NOT EXISTS servicos_catalogo (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT,
            duracao_minutos INTEGER NOT NULL DEFAULT 30,
            preco_pence INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS produtos_catalogo (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT,
            preco_pence INTEGER NOT NULL DEFAULT 0,
            imagem TEXT,
            ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

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
            telefone_id INTEGER,
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

    colunas_sms = {
        row["name"]
        for row in con.execute("PRAGMA table_info(sms_fila)")
    }
    if "telefone_id" not in colunas_sms:
        con.execute("ALTER TABLE sms_fila ADD COLUMN telefone_id INTEGER")

    con.execute("""
        CREATE TABLE IF NOT EXISTS modelos_comunicacao (
            id INTEGER PRIMARY KEY,
            chave TEXT NOT NULL UNIQUE,
            canal TEXT NOT NULL,
            nome TEXT NOT NULL,
            assunto TEXT,
            conteudo TEXT NOT NULL,
            conteudo_padrao TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    colunas_email_fila = {
        row["name"]
        for row in con.execute("PRAGMA table_info(email_fila)")
    }
    if "barbeiro_id" not in colunas_email_fila:
        con.execute("ALTER TABLE email_fila ADD COLUMN barbeiro_id INTEGER")

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

    colunas_log = {row["name"] for row in con.execute("PRAGMA table_info(atividade_log)")}
    for nome_coluna, tipo in (
        ("equipamento_id", "TEXT"), ("equipamento_nome", "TEXT"),
        ("equipamento_novo", "INTEGER NOT NULL DEFAULT 0"),
        ("utilizador_id", "INTEGER"), ("utilizador_nome", "TEXT"),
        ("utilizador_username", "TEXT"), ("dispositivo", "TEXT"), ("user_agent", "TEXT"),
        ("acao", "TEXT"), ("alvo_barbeiro_id", "INTEGER"), ("alvo_barbeiro_nome", "TEXT"),
        ("marcacao_id", "INTEGER")):
        if nome_coluna not in colunas_log:
            con.execute(f"ALTER TABLE atividade_log ADD COLUMN {nome_coluna} {tipo}")
    con.execute("""
        CREATE TABLE IF NOT EXISTS equipamentos (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL DEFAULT '',
            csrf_token TEXT NOT NULL,
            criado_em TEXT NOT NULL
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
            MAX(CASE WHEN m.estado = 'concluída' THEN m.inicio END) AS ultimo_corte,
            dono.username AS barbeiro_username,
            dono.nome AS barbeiro_nome
        FROM clientes c
        JOIN marcacoes m ON m.cliente_id = c.id
        LEFT JOIN utilizadores dono ON dono.id = c.barbeiro_id
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
    agora = agora_barbearia()
    data_pedida = request.args.get("data")
    vista_automatica = not data_pedida
    try:
        referencia = datetime.strptime(data_pedida, "%Y-%m-%d").date() if data_pedida else semana_por_defeito(agora)
    except ValueError:
        referencia = semana_por_defeito(agora)
        vista_automatica = True

    proxima_viragem = (agora + timedelta(days=(4 - agora.weekday()) % 7)).replace(
        hour=22, minute=0, second=0, microsecond=0)
    if proxima_viragem <= agora:
        proxima_viragem += timedelta(days=7)

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
    base_mes = agora.date().replace(day=1)

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
        """
        SELECT id, nome, username, avatar_path
        FROM utilizadores
        WHERE ativo = 1
          AND papel IN ('gestor', 'barbeiro')
          AND COALESCE(e_admin, 0) = 0
        ORDER BY
          CASE WHEN username = 'bruno' THEN 0 ELSE 1 END,
          nome COLLATE NOCASE
        """
    ).fetchall()
    barbeiro_pedido = request.args.get("barbeiro", "").strip()

    if barbeiro_pedido == "todos" and utilizador["e_admin"]:
        barbeiro_id = None
    elif barbeiro_pedido.isdigit() and any(b["id"] == int(barbeiro_pedido) for b in barbeiros) and pode_consultar_agenda(int(barbeiro_pedido)):
        barbeiro_id = int(barbeiro_pedido)
    else:
        # Por defeito cada utilizador abre a sua própria agenda.
        barbeiro_id = utilizador["id"]

    # A agenda aberta é a única origem válida para novas marcações.
    session["agenda_aberta_id"] = barbeiro_id

    filtro_barbeiro = " AND m.barbeiro_id = ?" if barbeiro_id else ""
    marcacoes = con.execute("""
        SELECT
            m.id,
            m.inicio,
            m.duracao_minutos,
            m.servico,
            m.estado,
            m.serie_id,
            m.valor_cobrado_centimos,
            m.fechado_em,
            c.nome,
            m.barbeiro_id,
            u.username AS barbeiro_username,
            u.nome AS barbeiro_nome
        FROM marcacoes AS m
        JOIN clientes AS c ON c.id = m.cliente_id
        LEFT JOIN utilizadores AS u ON u.id = m.barbeiro_id
        WHERE substr(m.inicio, 1, 10) BETWEEN ? AND ? AND m.estado != 'cancelada'""" + filtro_barbeiro + " ORDER BY m.inicio",
        (inicio_semana.isoformat(), fim_semana.isoformat(), *([barbeiro_id] if barbeiro_id else [])),
    ).fetchall()
    clientes_inativos = obter_clientes_inativos(con, apenas_pendentes=True)
    indisponibilidades = con.execute("""
        SELECT i.*, u.nome AS barbeiro_nome FROM indisponibilidades i
        LEFT JOIN utilizadores u ON u.id = i.barbeiro_id
        WHERE i.inicio < ? AND i.fim > ?
          AND (i.tipo = 'encerramento' OR i.barbeiro_id = ? OR ? = 1)
        ORDER BY i.inicio
    """, ((fim_semana + timedelta(days=1)).isoformat() + "T00:00", inicio_semana.isoformat() + "T00:00",
          barbeiro_id, int(gestor() and barbeiro_id is None))).fetchall()
    indisponibilidades = [dict(item, pode_eliminar=pode_gerir_indisponibilidade(item)) for item in indisponibilidades]
    for item in indisponibilidades:
        if item["tipo"] == "ausencia" and not gestor() and item["barbeiro_id"] != utilizador["id"]:
            item["motivo"] = "Indisponível"
    bloqueios = con.execute("""
        SELECT b.*, u.nome AS barbeiro_nome FROM bloqueios_pessoais b
        JOIN utilizadores u ON u.id = b.barbeiro_id
        WHERE b.inicio < ? AND datetime(b.inicio, '+' || b.duracao_minutos || ' minutes') > datetime(?)
          AND (b.barbeiro_id = ? OR ? = 1)
        ORDER BY b.inicio
    """, ((fim_semana + timedelta(days=1)).isoformat() + "T00:00", inicio_semana.isoformat() + "T00:00",
          barbeiro_id, int(gestor() and barbeiro_id is None))).fetchall()
    periodos_agenda = list(indisponibilidades)
    for item in bloqueios:
        periodo = dict(item, tipo="pessoal", motivo=item["descricao"],
            fim=(datetime.fromisoformat(item["inicio"]) + timedelta(minutes=item["duracao_minutos"])).isoformat(timespec="minutes"),
            pode_eliminar=gestor() or item["barbeiro_id"] == utilizador["id"])
        if not gestor() and item["barbeiro_id"] != utilizador["id"]:
            periodo["motivo"] = "Ocupado"
        periodos_agenda.append(periodo)
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
                "serie_id": m["serie_id"],
                "valor_cobrado_centimos": m["valor_cobrado_centimos"],
                "fechado_em": m["fechado_em"],
                "nome": m["nome"],
                "barbeiro_id": m["barbeiro_id"],
                "barbeiro_username": m["barbeiro_username"],
                "barbeiro_nome": m["barbeiro_nome"],
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

        periodos_dia = []
        inicio_grelha = datetime.combine(data_dia, datetime.min.time()).replace(hour=8)
        fim_grelha = inicio_grelha.replace(hour=23)
        for item in periodos_agenda:
            inicio_visual = max(datetime.fromisoformat(item["inicio"]), inicio_grelha)
            fim_visual = min(datetime.fromisoformat(item["fim"]), fim_grelha)
            if inicio_visual >= fim_visual:
                continue
            hora_base = inicio_visual.replace(minute=(inicio_visual.minute // 30) * 30, second=0, microsecond=0)
            periodos_dia.append(dict(item, hora_base=hora_base.strftime("%H:%M"),
                hora=inicio_visual.strftime("%H:%M"), hora_fim=fim_visual.strftime("%H:%M"),
                deslocamento=inicio_visual.minute-hora_base.minute,
                duracao=int((fim_visual-inicio_visual).total_seconds() // 60)))

        dias.append({
            "data": data_dia.isoformat(),
            "nome": nomes_dias[numero],
            "marcacoes": marcacoes_dia,
            "periodos": periodos_dia,
            "total": len(marcacoes_dia),
        })

    horas_grelha = []
    hora_atual = datetime.strptime("08:00", "%H:%M")
    hora_fim = datetime.strptime("23:00", "%H:%M")
    while hora_atual < hora_fim:
        horas_grelha.append(hora_atual.strftime("%H:%M"))
        hora_atual += timedelta(minutes=30)

    hoje = agora.date()
    inicio_semana_atual = hoje - timedelta(days=hoje.weekday())
    semana_atual = inicio_semana == inicio_semana_atual

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
        indisponibilidades=indisponibilidades,
        pode_consultar_outros=bool(utilizador["pode_consultar_agendas"]),
        pode_marcar_outros=bool(utilizador["pode_marcar_outros"]),
        total_semana=len(marcacoes),
        semana_atual=semana_atual,
        vista_automatica=vista_automatica,
        viragem_em_ms=int((proxima_viragem.timestamp() - agora.timestamp()) * 1000) if vista_automatica else None,
    )



@app.route("/estatisticas")
def estatisticas():
    con = get_db()
    utilizador = utilizador_atual()

    barbeiros = con.execute("""
        SELECT id, nome, username
        FROM utilizadores
        WHERE ativo = 1
          AND papel IN ('gestor', 'barbeiro')
          AND COALESCE(e_admin, 0) = 0
        ORDER BY
            CASE WHEN username = 'bruno' THEN 0 ELSE 1 END,
            nome COLLATE NOCASE
    """).fetchall()

    barbeiro_pedido = request.args.get("barbeiro", "").strip()

    if utilizador["papel"] == "gestor" or utilizador["e_admin"]:
        if barbeiro_pedido == "todos":
            barbeiro_id = None
        elif barbeiro_pedido.isdigit() and any(
            b["id"] == int(barbeiro_pedido)
            for b in barbeiros
        ):
            barbeiro_id = int(barbeiro_pedido)
        else:
            # Bruno vê as suas estatísticas por defeito
            barbeiro_id = utilizador["id"]
    else:
        # Ricardo/Maia só podem ver as próprias
        barbeiro_id = utilizador["id"]

    filtro = ""
    parametros_barbeiro = []

    if barbeiro_id is not None:
        filtro = " AND barbeiro_id = ?"
        parametros_barbeiro = [barbeiro_id]

    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())
    fim_semana = inicio_semana + timedelta(days=6)

    inicio_mes = hoje.replace(day=1)

    if hoje.month == 12:
        inicio_mes_seguinte = date(hoje.year + 1, 1, 1)
    else:
        inicio_mes_seguinte = date(
            hoje.year,
            hoje.month + 1,
            1
        )

    inicio_ano = date(hoje.year, 1, 1)
    inicio_ano_seguinte = date(hoje.year + 1, 1, 1)

    def contar_entre(inicio_data, fim_data):
        return con.execute(
            """
            SELECT COUNT(*)
            FROM marcacoes
            WHERE estado = 'concluída'
              AND substr(inicio, 1, 10) >= ?
              AND substr(inicio, 1, 10) < ?
            """ + filtro,
            (
                inicio_data.isoformat(),
                fim_data.isoformat(),
                *parametros_barbeiro
            )
        ).fetchone()[0]

    cortes_hoje = con.execute(
        """
        SELECT COUNT(*)
        FROM marcacoes
        WHERE estado = 'concluída'
          AND substr(inicio, 1, 10) = ?
        """ + filtro,
        (
            hoje.isoformat(),
            *parametros_barbeiro
        )
    ).fetchone()[0]

    historico_mensal = con.execute(
        """
        SELECT
            substr(inicio, 1, 7) AS mes,
            COUNT(*) AS total
        FROM marcacoes
        WHERE estado = 'concluída'
        """ + filtro + """
        GROUP BY substr(inicio, 1, 7)
        ORDER BY mes DESC
        """,
        parametros_barbeiro
    ).fetchall()

    def receita_entre(inicio_data, fim_data):
        return con.execute(
            """
            SELECT COALESCE(SUM(valor_cobrado_centimos), 0)
            FROM marcacoes
            WHERE estado = 'concluída'
              AND valor_cobrado_centimos IS NOT NULL
              AND substr(inicio, 1, 10) >= ?
              AND substr(inicio, 1, 10) < ?
            """ + filtro,
            (inicio_data.isoformat(), fim_data.isoformat(), *parametros_barbeiro)
        ).fetchone()[0]

    receita_hoje = con.execute(
        """
        SELECT COALESCE(SUM(valor_cobrado_centimos), 0)
        FROM marcacoes
        WHERE estado = 'concluída'
          AND valor_cobrado_centimos IS NOT NULL
          AND substr(inicio, 1, 10) = ?
        """ + filtro,
        (hoje.isoformat(), *parametros_barbeiro)
    ).fetchone()[0]

    receita = {
        "hoje": receita_hoje,
        "semana": receita_entre(inicio_semana, fim_semana + timedelta(days=1)),
        "mes": receita_entre(inicio_mes, inicio_mes_seguinte),
        "ano": receita_entre(inicio_ano, inicio_ano_seguinte),
    }

    historico_receita = con.execute(
        """
        SELECT substr(inicio, 1, 7) AS mes,
               COUNT(CASE WHEN valor_cobrado_centimos IS NOT NULL THEN 1 END) AS pagos,
               COALESCE(SUM(valor_cobrado_centimos), 0) AS valor_centimos
        FROM marcacoes
        WHERE estado = 'concluída'
        """ + filtro + """
        GROUP BY substr(inicio, 1, 7)
        ORDER BY mes DESC
        """,
        parametros_barbeiro
    ).fetchall()

    dados = {
        "hoje": cortes_hoje,
        "semana": contar_entre(
            inicio_semana,
            fim_semana + timedelta(days=1)
        ),
        "mes": contar_entre(
            inicio_mes,
            inicio_mes_seguinte
        ),
        "ano": contar_entre(
            inicio_ano,
            inicio_ano_seguinte
        ),
    }

    con.close()

    return render_template(
        "estatisticas.html",
        estatisticas=dados,
        receita=receita,
        historico_mensal=historico_mensal,
        historico_receita=historico_receita,
        utilizador=utilizador,
        barbeiros=barbeiros,
        barbeiro_selecionado=barbeiro_id,
    )



@app.route("/contabilidade")
def contabilidade():
    con = get_db()
    utilizador = utilizador_atual()

    pode_ver_todos = bool(
        utilizador
        and (
            utilizador["e_admin"]
            or utilizador["papel"] == "gestor"
        )
    )

    barbeiros = con.execute("""
        SELECT id, nome, username
        FROM utilizadores
        WHERE ativo = 1
          AND papel IN ('gestor', 'barbeiro')
          AND COALESCE(e_admin, 0) = 0
        ORDER BY
            CASE WHEN username = 'bruno' THEN 0 ELSE 1 END,
            nome COLLATE NOCASE
    """).fetchall()

    barbeiro_pedido = request.args.get("barbeiro", "").strip()

    # Bruno/gestor e admin podem consultar:
    # - total Blessed
    # - Bruno
    # - Ricardo
    # - Maia
    #
    # Barbeiros normais ficam SEMPRE presos ao próprio ID,
    # mesmo que tentem alterar a URL manualmente.
    if pode_ver_todos:
        if barbeiro_pedido == "todos" or not barbeiro_pedido:
            barbeiro_id = None
        elif barbeiro_pedido.isdigit() and any(
            b["id"] == int(barbeiro_pedido)
            for b in barbeiros
        ):
            barbeiro_id = int(barbeiro_pedido)
        else:
            barbeiro_id = None
    else:
        barbeiro_id = utilizador["id"]

    filtro = ""
    parametros_barbeiro = []

    if barbeiro_id is not None:
        filtro = " AND barbeiro_id = ?"
        parametros_barbeiro = [barbeiro_id]

    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())
    inicio_mes = hoje.replace(day=1)

    if hoje.month == 12:
        inicio_mes_seguinte = date(hoje.year + 1, 1, 1)
    else:
        inicio_mes_seguinte = date(
            hoje.year,
            hoje.month + 1,
            1
        )

    inicio_ano = date(hoje.year, 1, 1)
    inicio_ano_seguinte = date(hoje.year + 1, 1, 1)

    def resumo_entre(inicio_data, fim_data):
        return con.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(valor_cobrado_centimos), 0) AS valor
            FROM marcacoes
            WHERE estado = 'concluída'
              AND valor_cobrado_centimos IS NOT NULL
              AND substr(inicio, 1, 10) >= ?
              AND substr(inicio, 1, 10) < ?
            """ + filtro,
            (
                inicio_data.isoformat(),
                fim_data.isoformat(),
                *parametros_barbeiro
            )
        ).fetchone()

    hoje_resumo = con.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(valor_cobrado_centimos), 0) AS valor
        FROM marcacoes
        WHERE estado = 'concluída'
          AND valor_cobrado_centimos IS NOT NULL
          AND substr(inicio, 1, 10) = ?
        """ + filtro,
        (
            hoje.isoformat(),
            *parametros_barbeiro
        )
    ).fetchone()

    resumo = {
        "hoje": hoje_resumo,
        "semana": resumo_entre(
            inicio_semana,
            inicio_semana + timedelta(days=7)
        ),
        "mes": resumo_entre(
            inicio_mes,
            inicio_mes_seguinte
        ),
        "ano": resumo_entre(
            inicio_ano,
            inicio_ano_seguinte
        ),
    }

    historico = con.execute(
        """
        SELECT
            substr(inicio, 1, 7) AS mes,
            COUNT(*) AS total,
            COALESCE(SUM(valor_cobrado_centimos), 0) AS valor
        FROM marcacoes
        WHERE estado = 'concluída'
          AND valor_cobrado_centimos IS NOT NULL
        """ + filtro + """
        GROUP BY substr(inicio, 1, 7)
        ORDER BY mes DESC
        """,
        parametros_barbeiro
    ).fetchall()

    # Só Bruno/gestor e admin recebem do servidor
    # os totais separados dos restantes barbeiros.
    por_barbeiro = []

    if pode_ver_todos:
        por_barbeiro = con.execute(
            """
            SELECT
                u.id,
                u.nome,
                COUNT(m.id) AS total,
                COALESCE(SUM(m.valor_cobrado_centimos), 0) AS valor
            FROM utilizadores u
            LEFT JOIN marcacoes m
              ON m.barbeiro_id = u.id
             AND m.estado = 'concluída'
             AND m.valor_cobrado_centimos IS NOT NULL
             AND substr(m.inicio, 1, 7) = ?
            WHERE u.ativo = 1
              AND u.papel IN ('gestor', 'barbeiro')
              AND COALESCE(u.e_admin, 0) = 0
            GROUP BY u.id, u.nome, u.username
            ORDER BY
                CASE WHEN u.username = 'bruno' THEN 0 ELSE 1 END,
                u.nome COLLATE NOCASE
            """,
            (hoje.strftime("%Y-%m"),)
        ).fetchall()


    # Recebimentos por método, usando a data do fecho financeiro.
    def recebimentos_por_metodo(inicio, fim):
        linhas = con.execute(
            """
            SELECT
                COALESCE(NULLIF(metodo_pagamento, ''), 'sem_metodo') AS metodo,
                COUNT(*) AS quantidade,
                COALESCE(SUM(valor_cobrado_centimos), 0) AS valor
            FROM marcacoes
            WHERE valor_cobrado_centimos IS NOT NULL
              AND fechado_em IS NOT NULL
              AND substr(fechado_em, 1, 10) >= ?
              AND substr(fechado_em, 1, 10) < ?
            """ + filtro,
            (inicio.isoformat(), fim.isoformat(), *parametros_barbeiro)
        ).fetchall()

        valores = {
            "mbway": 0,
            "cash": 0,
            "sem_metodo": 0,
        }
        for linha in linhas:
            metodo = linha["metodo"]
            valores[metodo if metodo in valores else "sem_metodo"] += linha["valor"]
        valores["total"] = sum(valores.values())
        return valores

    recebimentos = {
        "hoje": recebimentos_por_metodo(hoje, hoje + timedelta(days=1)),
        "semana": recebimentos_por_metodo(
            inicio_semana, inicio_semana + timedelta(days=7)
        ),
        "mes": recebimentos_por_metodo(inicio_mes, inicio_mes_seguinte),
    }

    con.close()

    return render_template(
        "contabilidade.html",
        utilizador=utilizador,
        barbeiros=barbeiros if pode_ver_todos else [],
        barbeiro_selecionado=barbeiro_id,
        resumo=resumo,
        historico=historico,
        por_barbeiro=por_barbeiro,
        recebimentos=recebimentos,
        pode_ver_todos=pode_ver_todos,
    )



@app.route("/admin")
@requer_admin
def admin():
    con = get_db()

    utilizadores = con.execute("""
        SELECT
            u.id,
            u.nome,
            u.username,
            u.avatar_path,
            u.papel,
            u.ativo,
            u.pode_consultar_agendas,
            u.pode_marcar_outros,
            u.sms_autorizado,
            u.sms_provider,
            u.email_ativo,
            u.email_confirmacao,
            u.email_lembrete_24h,
            u.email_lembrete_1h,
            u.e_admin,
            (
                SELECT COUNT(*)
                FROM clientes c
                WHERE c.barbeiro_id = u.id
            ) AS total_clientes,
            (
                SELECT COUNT(*)
                FROM marcacoes m
                WHERE m.barbeiro_id = u.id
            ) AS total_marcacoes
        FROM utilizadores u
        ORDER BY
            u.e_admin DESC,
            CASE WHEN u.username = 'bruno' THEN 0 ELSE 1 END,
            u.nome COLLATE NOCASE
    """).fetchall()

    total_clientes = con.execute(
        "SELECT COUNT(*) FROM clientes"
    ).fetchone()[0]

    total_marcacoes = con.execute(
        "SELECT COUNT(*) FROM marcacoes"
    ).fetchone()[0]

    produtos = con.execute("""
        SELECT
            id,
            nome,
            descricao,
            preco_pence,
            imagem,
            ativo
        FROM produtos_catalogo
        ORDER BY ativo DESC, nome COLLATE NOCASE
    """).fetchall()

    servicos = con.execute("""
        SELECT
            id,
            nome,
            descricao,
            duracao_minutos,
            preco_pence,
            ativo
        FROM servicos_catalogo
        ORDER BY ativo DESC, nome COLLATE NOCASE
    """).fetchall()

    modelos_comunicacao = con.execute("""
        SELECT
            id,
            chave,
            canal,
            nome,
            assunto,
            conteudo,
            conteudo_padrao,
            ativo
        FROM modelos_comunicacao
        ORDER BY
            CASE canal
                WHEN 'sms' THEN 0
                WHEN 'email' THEN 1
                ELSE 2
            END,
            id
    """).fetchall()

    clientes_admin = con.execute("""
        SELECT
            c.id,
            c.nome,
            c.email,
            c.barbeiro_id,
            u.nome AS barbeiro,
            u.username AS barbeiro_username,

            (
                SELECT t.numero
                FROM telefones t
                WHERE t.cliente_id = c.id
                  AND t.atual = 1
                ORDER BY t.id DESC
                LIMIT 1
            ) AS telefone,

            (
                SELECT COUNT(*)
                FROM marcacoes m
                WHERE m.cliente_id = c.id
            ) AS total_marcacoes

        FROM clientes c
        LEFT JOIN utilizadores u
          ON u.id = c.barbeiro_id

        ORDER BY c.nome COLLATE NOCASE
    """).fetchall()

    db_path_admin = Path("blessed.db")

    sistema_admin = {
        "db_existe": db_path_admin.exists(),
        "db_tamanho_mb": (
            round(db_path_admin.stat().st_size / 1024 / 1024, 2)
            if db_path_admin.exists()
            else 0
        ),
    }

    pasta_backups = DB.parent / "backups"

    backups_admin = []

    if pasta_backups.exists():
        backups_admin = [
            {
                "nome": f.name,
                "tamanho_mb": round(f.stat().st_size / 1024 / 1024, 2),
            }
            for f in sorted(
                pasta_backups.glob("blessed-*.db"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )[:10]
        ]

    logs_admin = con.execute("""
        SELECT *
        FROM atividade_log
        ORDER BY id DESC
        LIMIT 200
    """).fetchall()

    con.close()

    return render_template(
        "admin.html",
        utilizadores=utilizadores,
        total_clientes=total_clientes,
        total_marcacoes=total_marcacoes,
        produtos=produtos,
        servicos=servicos,
        modelos_comunicacao=modelos_comunicacao,
        clientes_admin=clientes_admin,
        sistema_admin=sistema_admin,
        backups_admin=backups_admin,
        logs_admin=logs_admin,
        logs_email_destino=LOG_EMAIL_DESTINO,
        utilizador=utilizador_atual(),
    )



@app.route("/admin/logs/enviar", methods=["POST"])
@requer_admin
def admin_logs_enviar():
    modo = request.form.get("modo", "lote")
    con = get_db()
    if modo == "lote":
        try:
            limite = int(request.form.get("lote", "50"))
        except ValueError:
            limite = 50
        if limite not in (50, 100, 150):
            con.close()
            return "Lote inválido", 400
        rows = con.execute("""
            SELECT *
            FROM atividade_log WHERE enviado_em IS NULL
            ORDER BY id DESC LIMIT ?
        """, (limite,)).fetchall()
        descricao = f"últimos {len(rows)} logs pendentes"
    elif modo == "datas":
        inicio = request.form.get("data_inicio", "").strip()
        fim = request.form.get("data_fim", "").strip()
        if not inicio or not fim or inicio > fim:
            con.close()
            return "Intervalo de datas inválido", 400
        rows = con.execute("""
            SELECT *
            FROM atividade_log
            WHERE date(criado_em) BETWEEN ? AND ?
            ORDER BY id
        """, (inicio, fim)).fetchall()
        descricao = f"{inicio} a {fim}"
    else:
        con.close()
        return "Modo inválido", 400

    enviado = _enviar_logs_email(rows, descricao)
    if enviado and rows:
        agora = datetime.now().astimezone().isoformat(timespec="seconds")
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        con.execute(f"UPDATE atividade_log SET enviado_em = ? WHERE id IN ({placeholders})", [agora, *ids])
        con.commit()
    con.close()
    if not enviado:
        return "Não foi possível enviar os logs por email", 502
    return redirect(url_for("admin") + "#admin-logs")


@app.route("/admin/modelos/<int:modelo_id>/guardar", methods=["POST"])
@requer_admin
def admin_modelo_guardar(modelo_id):
    conteudo = request.form.get("conteudo", "").strip()
    assunto = request.form.get("assunto", "").strip()
    ativo = 1 if request.form.get("ativo") == "1" else 0

    if not conteudo:
        return "O conteúdo da mensagem não pode ficar vazio", 400

    con = get_db()

    modelo = con.execute("""
        SELECT id, canal
        FROM modelos_comunicacao
        WHERE id = ?
    """, (modelo_id,)).fetchone()

    if not modelo:
        con.close()
        return "Modelo não encontrado", 404

    if modelo["canal"] != "email":
        assunto = None

    con.execute("""
        UPDATE modelos_comunicacao
        SET assunto = ?,
            conteudo = ?,
            ativo = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        assunto or None,
        conteudo,
        ativo,
        modelo_id,
    ))

    con.commit()
    con.close()

    return redirect(url_for("admin") + "#admin-modelos")


@app.route("/admin/modelos/<int:modelo_id>/repor", methods=["POST"])
@requer_admin
def admin_modelo_repor(modelo_id):
    con = get_db()

    modelo = con.execute("""
        SELECT id
        FROM modelos_comunicacao
        WHERE id = ?
    """, (modelo_id,)).fetchone()

    if not modelo:
        con.close()
        return "Modelo não encontrado", 404

    con.execute("""
        UPDATE modelos_comunicacao
        SET conteudo = conteudo_padrao,
            ativo = 1,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (modelo_id,))

    con.commit()
    con.close()

    return redirect(url_for("admin") + "#admin-modelos")



@app.route("/admin/campanhas/preparar", methods=["POST"])
@requer_admin
def admin_campanha_preparar():
    tipo = request.form.get("tipo", "").strip()
    canal = request.form.get("canal", "").strip()
    barbeiro = request.form.get("barbeiro_id", "todos").strip()
    assunto = request.form.get("assunto", "").strip()
    mensagem = request.form.get("mensagem", "").strip()

    tipos_validos = {
        "natal",
        "ano_novo",
        "ferias",
        "livre",
    }

    canais_validos = {
        "sms",
        "email",
        "ambos",
    }

    if tipo not in tipos_validos:
        return "Tipo de campanha inválido", 400

    if canal not in canais_validos:
        return "Canal inválido", 400

    if not mensagem:
        return "A mensagem não pode ficar vazia", 400

    if canal in ("email", "ambos") and not assunto:
        return "O assunto é obrigatório para email", 400

    con = get_db()

    barbeiro_id = None

    if barbeiro != "todos":
        try:
            barbeiro_id = int(barbeiro)
        except ValueError:
            con.close()
            return "Barbeiro inválido", 400

        profissional = con.execute("""
            SELECT id
            FROM utilizadores
            WHERE id = ?
              AND ativo = 1
              AND COALESCE(e_admin, 0) = 0
        """, (barbeiro_id,)).fetchone()

        if not profissional:
            con.close()
            return "Barbeiro não encontrado", 404

    filtros = []
    parametros = []

    if barbeiro_id is not None:
        filtros.append("c.barbeiro_id = ?")
        parametros.append(barbeiro_id)

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    clientes = con.execute(f"""
        SELECT
            c.id,
            c.nome,
            c.email,
            c.barbeiro_id,
            u.nome AS barbeiro,
            (
                SELECT t.numero
                FROM telefones t
                WHERE t.cliente_id = c.id
                  AND t.atual = 1
                ORDER BY t.id DESC
                LIMIT 1
            ) AS telefone
        FROM clientes c
        LEFT JOIN utilizadores u
          ON u.id = c.barbeiro_id
        {where}
        ORDER BY c.nome COLLATE NOCASE
    """, parametros).fetchall()

    total_clientes = len(clientes)

    total_sms = sum(
        1 for c in clientes
        if c["telefone"]
    )

    total_email = sum(
        1 for c in clientes
        if c["email"]
    )

    if canal == "sms":
        total_destinatarios = total_sms
    elif canal == "email":
        total_destinatarios = total_email
    else:
        total_destinatarios = total_sms + total_email

    cur = con.execute("""
        INSERT INTO campanhas
        (
            titulo,
            nome,
            tipo,
            canal,
            barbeiro_id,
            assunto,
            mensagem,
            estado,
            total_destinatarios,
            criado_por_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'rascunho', ?, ?)
    """, (
        {
            "natal": "Natal",
            "ano_novo": "Ano Novo",
            "ferias": "Férias / Encerramento",
            "livre": "Mensagem livre",
        }[tipo],
        {
            "natal": "Natal",
            "ano_novo": "Ano Novo",
            "ferias": "Férias / Encerramento",
            "livre": "Mensagem livre",
        }[tipo],
        tipo,
        canal,
        barbeiro_id,
        assunto or None,
        mensagem,
        total_destinatarios,
        utilizador_atual()["id"],
    ))

    campanha_id = cur.lastrowid

    con.commit()

    campanha = con.execute("""
        SELECT
            c.*,
            u.nome AS barbeiro
        FROM campanhas c
        LEFT JOIN utilizadores u
          ON u.id = c.barbeiro_id
        WHERE c.id = ?
    """, (campanha_id,)).fetchone()

    con.close()

    return render_template(
        "campanha_preview.html",
        campanha=campanha,
        total_clientes=total_clientes,
        total_sms=total_sms,
        total_email=total_email,
    )


@app.route("/admin/campanhas/<int:campanha_id>/confirmar", methods=["POST"])
@requer_admin
def admin_campanha_confirmar(campanha_id):
    con = get_db()

    campanha = con.execute("""
        SELECT *
        FROM campanhas
        WHERE id = ?
          AND estado = 'rascunho'
    """, (campanha_id,)).fetchone()

    if not campanha:
        con.close()
        return "Campanha não encontrada ou já confirmada", 404

    filtros = []
    parametros = []

    if campanha["barbeiro_id"] is not None:
        filtros.append("c.barbeiro_id = ?")
        parametros.append(campanha["barbeiro_id"])

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    clientes = con.execute(f"""
        SELECT
            c.id,
            c.nome,
            c.email,
            (
                SELECT t.numero
                FROM telefones t
                WHERE t.cliente_id = c.id
                  AND t.atual = 1
                ORDER BY t.id DESC
                LIMIT 1
            ) AS telefone
        FROM clientes c
        {where}
        ORDER BY c.id
    """, parametros).fetchall()

    total = 0

    try:
        for cliente in clientes:

            if campanha["canal"] in ("sms", "ambos") and cliente["telefone"]:
                con.execute("""
                    INSERT INTO campanha_destinatarios
                    (
                        campanha_id,
                        cliente_id,
                        canal,
                        destino,
                        estado
                    )
                    VALUES (?, ?, 'sms', ?, 'pendente')
                """, (
                    campanha_id,
                    cliente["id"],
                    cliente["telefone"],
                ))
                total += 1

            if campanha["canal"] in ("email", "ambos") and cliente["email"]:
                con.execute("""
                    INSERT INTO campanha_destinatarios
                    (
                        campanha_id,
                        cliente_id,
                        canal,
                        destino,
                        estado
                    )
                    VALUES (?, ?, 'email', ?, 'pendente')
                """, (
                    campanha_id,
                    cliente["id"],
                    cliente["email"],
                ))
                total += 1

        con.execute("""
            UPDATE campanhas
            SET estado = 'confirmada',
                total_destinatarios = ?,
                confirmado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            total,
            campanha_id,
        ))

        con.commit()

    except Exception:
        con.rollback()
        con.close()
        raise

    con.close()

    return redirect(url_for("admin") + "#admin-campanhas")


@app.route("/admin/campanhas/<int:campanha_id>/cancelar", methods=["POST"])
@requer_admin
def admin_campanha_cancelar(campanha_id):
    con = get_db()

    con.execute("""
        UPDATE campanhas
        SET estado = 'cancelada'
        WHERE id = ?
          AND estado = 'rascunho'
    """, (campanha_id,))

    con.commit()
    con.close()

    return redirect(url_for("admin") + "#admin-campanhas")



@app.route("/admin/sistema/backup", methods=["POST"])
@requer_admin
def admin_sistema_backup():
    origem = DB

    if not origem.exists():
        return "Base de dados não encontrada", 404

    pasta = DB.parent / "backups"
    pasta.mkdir(parents=True, exist_ok=True)

    nome = datetime.now().strftime(
        "blessed-%Y%m%d-%H%M%S.db"
    )

    destino = pasta / nome

    # SQLite online backup keeps the copy consistent while writes are active.
    with sqlite3.connect(origem) as fonte, sqlite3.connect(destino) as copia:
        fonte.backup(copia)

    return redirect(
        url_for("admin") + "#admin-sistema"
    )


@app.route("/admin/utilizadores/novo", methods=["POST"])
@requer_admin
def admin_novo_utilizador():
    nome = request.form.get("nome", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")

    if not nome or not username or not password:
        return "Nome, username e password são obrigatórios", 400

    con = get_db()

    try:
        con.execute("""
            INSERT INTO utilizadores
            (
                nome,
                username,
                password_hash,
                papel,
                ativo,
                pode_consultar_agendas,
                pode_marcar_outros,
                sms_autorizado,
                sms_provider,
                e_admin
            )
            VALUES (?, ?, ?, 'barbeiro', 1, 0, 0, 0, NULL, 0)
        """, (
            nome,
            username,
            generate_password_hash(password),
        ))

        con.commit()

    except sqlite3.IntegrityError:
        con.rollback()
        con.close()
        return "Esse username já existe", 409

    con.close()
    return redirect(url_for("admin"))


@app.route("/admin/utilizadores/<int:utilizador_id>/guardar", methods=["POST"])
@requer_admin
def admin_guardar_utilizador(utilizador_id):
    con = get_db()

    atual = con.execute("""
        SELECT *
        FROM utilizadores
        WHERE id = ?
    """, (utilizador_id,)).fetchone()

    if not atual:
        con.close()
        return "Utilizador não encontrado", 404

    nome = request.form.get("nome", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")

    avatar_path = atual["avatar_path"] if "avatar_path" in atual.keys() else None
    remover_avatar = request.form.get("remover_avatar") == "1"
    avatar_upload = request.files.get("avatar")
    if remover_avatar:
        if avatar_path:
            antigo = Path(app.static_folder) / avatar_path
            if antigo.exists() and antigo.is_file():
                antigo.unlink()
        avatar_path = None
    elif avatar_upload and avatar_upload.filename:
        extensao = Path(avatar_upload.filename).suffix.lower()
        if extensao not in {".jpg", ".jpeg", ".png", ".webp"}:
            con.close()
            return "Avatar inválido. Usa JPG, PNG ou WEBP", 400
        pasta_avatar = Path(app.static_folder) / "avatars"
        pasta_avatar.mkdir(parents=True, exist_ok=True)
        nome_avatar = f"user-{utilizador_id}-{secrets.token_hex(6)}{extensao}"
        destino_avatar = pasta_avatar / nome_avatar
        avatar_upload.save(destino_avatar)
        if avatar_path:
            antigo = Path(app.static_folder) / avatar_path
            if antigo.exists() and antigo.is_file() and antigo != destino_avatar:
                antigo.unlink()
        avatar_path = f"avatars/{nome_avatar}"

    ativo = 1 if request.form.get("ativo") == "1" else 0
    consultar = 1 if request.form.get("pode_consultar_agendas") == "1" else 0
    marcar = 1 if request.form.get("pode_marcar_outros") == "1" else 0
    sms = 1 if request.form.get("sms_autorizado") == "1" else 0

    email_ativo = 1 if request.form.get("email_ativo") == "1" else 0
    email_confirmacao = 1 if request.form.get("email_confirmacao") == "1" else 0
    email_lembrete_24h = 1 if request.form.get("email_lembrete_24h") == "1" else 0
    email_lembrete_1h = 1 if request.form.get("email_lembrete_1h") == "1" else 0

    # A própria conta admin não pode ser desativada pela página.
    if atual["e_admin"]:
        ativo = 1
        sms = 0
        email_ativo = 0
        email_confirmacao = 0
        email_lembrete_24h = 0
        email_lembrete_1h = 0

    if not nome or not username:
        con.close()
        return "Nome e username são obrigatórios", 400

    try:
        con.execute("""
            UPDATE utilizadores
            SET nome = ?,
                username = ?,
                ativo = ?,
                pode_consultar_agendas = ?,
                pode_marcar_outros = ?,
                sms_autorizado = ?,
                email_ativo = ?,
                email_confirmacao = ?,
                email_lembrete_24h = ?,
                email_lembrete_1h = ?,
                avatar_path = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            nome,
            username,
            ativo,
            consultar,
            marcar,
            sms,
            email_ativo,
            email_confirmacao,
            email_lembrete_24h,
            email_lembrete_1h,
            avatar_path,
            utilizador_id,
        ))

        if password:
            con.execute("""
                UPDATE utilizadores
                SET password_hash = ?,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                generate_password_hash(password),
                utilizador_id,
            ))

        con.commit()

    except sqlite3.IntegrityError:
        con.rollback()
        con.close()
        return "Esse username já existe", 409

    con.close()
    return redirect(url_for("admin"))


@app.route("/admin/utilizadores/<int:utilizador_id>/apagar", methods=["POST"])
@requer_admin
def admin_apagar_utilizador(utilizador_id):
    utilizador = utilizador_atual()

    if utilizador_id == utilizador["id"]:
        return "Não podes apagar a tua própria conta administrativa", 400

    con = get_db()

    alvo = con.execute("""
        SELECT id, nome, e_admin
        FROM utilizadores
        WHERE id = ?
    """, (utilizador_id,)).fetchone()

    if not alvo:
        con.close()
        return "Utilizador não encontrado", 404

    if alvo["e_admin"]:
        con.close()
        return "Uma conta administrativa não pode ser apagada aqui", 400

    total_clientes = con.execute("""
        SELECT COUNT(*)
        FROM clientes
        WHERE barbeiro_id = ?
    """, (utilizador_id,)).fetchone()[0]

    total_marcacoes = con.execute("""
        SELECT COUNT(*)
        FROM marcacoes
        WHERE barbeiro_id = ?
    """, (utilizador_id,)).fetchone()[0]

    if total_clientes or total_marcacoes:
        con.close()
        return (
            "Este barbeiro tem histórico. "
            "Desativa-o em vez de o apagar."
        ), 409

    con.execute(
        "DELETE FROM utilizadores WHERE id = ?",
        (utilizador_id,)
    )

    con.commit()
    con.close()

    return redirect(url_for("admin"))




@app.route("/admin/produtos/novo", methods=["POST"])
@requer_admin
def admin_produto_novo():
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()
    imagem = request.form.get("imagem", "").strip()

    try:
        preco = float(
            request.form.get("preco", "0")
            .strip()
            .replace(",", ".")
        )
    except ValueError:
        return "Preço inválido", 400

    if not nome or preco < 0:
        return "Nome e preço válido são obrigatórios", 400

    preco_pence = round(preco * 100)

    con = get_db()

    con.execute("""
        INSERT INTO produtos_catalogo
            (nome, descricao, preco_pence, imagem, ativo)
        VALUES (?, ?, ?, ?, 1)
    """, (
        nome,
        descricao or None,
        preco_pence,
        imagem or None,
    ))

    con.commit()
    con.close()

    return redirect(url_for("admin"))


@app.route("/admin/produtos/<int:produto_id>/guardar", methods=["POST"])
@requer_admin
def admin_produto_guardar(produto_id):
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()
    imagem = request.form.get("imagem", "").strip()
    ativo = 1 if request.form.get("ativo") == "1" else 0

    try:
        preco = float(
            request.form.get("preco", "0")
            .strip()
            .replace(",", ".")
        )
    except ValueError:
        return "Preço inválido", 400

    if not nome or preco < 0:
        return "Dados inválidos", 400

    con = get_db()

    existe = con.execute("""
        SELECT id
        FROM produtos_catalogo
        WHERE id = ?
    """, (produto_id,)).fetchone()

    if not existe:
        con.close()
        return "Produto não encontrado", 404

    con.execute("""
        UPDATE produtos_catalogo
        SET nome = ?,
            descricao = ?,
            preco_pence = ?,
            imagem = ?,
            ativo = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        nome,
        descricao or None,
        round(preco * 100),
        imagem or None,
        ativo,
        produto_id,
    ))

    con.commit()
    con.close()

    return redirect(url_for("admin"))


@app.route("/admin/produtos/<int:produto_id>/apagar", methods=["POST"])
@requer_admin
def admin_produto_apagar(produto_id):
    con = get_db()

    con.execute("""
        DELETE FROM produtos_catalogo
        WHERE id = ?
    """, (produto_id,))

    con.commit()
    con.close()

    return redirect(url_for("admin"))


@app.route("/servicos")
def servicos():
    con = get_db()

    servicos_lista = con.execute("""
        SELECT
            id,
            nome,
            descricao,
            duracao_minutos,
            preco_pence
        FROM servicos_catalogo
        WHERE ativo = 1
        ORDER BY nome COLLATE NOCASE
    """).fetchall()

    con.close()

    return render_template(
        "servicos.html",
        servicos=servicos_lista,
    )



@app.route("/admin/servicos/novo", methods=["POST"])
@requer_admin
def admin_servico_novo():
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()

    try:
        duracao = int(request.form.get("duracao", "30"))
        preco = float(
            request.form.get("preco", "0")
            .strip()
            .replace(",", ".")
        )
    except ValueError:
        return "Duração ou preço inválido", 400

    if not nome or duracao <= 0 or preco < 0:
        return "Dados inválidos", 400

    con = get_db()

    con.execute("""
        INSERT INTO servicos_catalogo
        (nome, descricao, duracao_minutos, preco_pence, ativo)
        VALUES (?, ?, ?, ?, 1)
    """, (
        nome,
        descricao or None,
        duracao,
        round(preco * 100),
    ))

    con.commit()
    con.close()

    return redirect(url_for("admin"))


@app.route("/admin/servicos/<int:servico_id>/guardar", methods=["POST"])
@requer_admin
def admin_servico_guardar(servico_id):
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip()
    ativo = 1 if request.form.get("ativo") == "1" else 0

    try:
        duracao = int(request.form.get("duracao", "30"))
        preco = float(
            request.form.get("preco", "0")
            .strip()
            .replace(",", ".")
        )
    except ValueError:
        return "Duração ou preço inválido", 400

    if not nome or duracao <= 0 or preco < 0:
        return "Dados inválidos", 400

    con = get_db()

    con.execute("""
        UPDATE servicos_catalogo
        SET nome = ?,
            descricao = ?,
            duracao_minutos = ?,
            preco_pence = ?,
            ativo = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        nome,
        descricao or None,
        duracao,
        round(preco * 100),
        ativo,
        servico_id,
    ))

    con.commit()
    con.close()

    return redirect(url_for("admin"))


@app.route("/admin/servicos/<int:servico_id>/apagar", methods=["POST"])
@requer_admin
def admin_servico_apagar(servico_id):
    con = get_db()

    con.execute(
        "DELETE FROM servicos_catalogo WHERE id = ?",
        (servico_id,)
    )

    con.commit()
    con.close()

    return redirect(url_for("admin"))


@app.route("/produtos")
def produtos():
    con = get_db()

    rows = con.execute("""
        SELECT id, nome, descricao, preco_pence, imagem
        FROM produtos_catalogo
        WHERE ativo = 1
        ORDER BY nome COLLATE NOCASE
    """).fetchall()

    con.close()

    produtos_lista = []

    for row in rows:
        preco = f"{row['preco_pence'] / 100:.2f}".replace(".", ",") + " £"

        produtos_lista.append({
            "id": row["id"],
            "nome": row["nome"],
            "descricao": row["descricao"] or "",
            "preco": preco,
            "imagem": row["imagem"] or "",
        })

    return render_template(
        "produtos.html",
        produtos=produtos_lista,
    )

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
    utilizador = utilizador_atual()

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
        LEFT JOIN utilizadores dono
            ON dono.id = c.barbeiro_id
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
        utilizador=utilizador,
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
    utilizador = utilizador_atual()

    barbeiro_id = request.form.get("barbeiro_id", type=int) if gestor() else utilizador["id"]

    if not barbeiro_id:
        barbeiro_id = utilizador["id"]

    if gestor():
        profissional = cur.execute(
            "SELECT id FROM utilizadores WHERE id = ? AND ativo = 1",
            (barbeiro_id,)
        ).fetchone()
        if not profissional:
            con.close()
            return "Barbeiro inválido", 400

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
            INSERT INTO clientes (nome, email, data_nascimento, barbeiro_id)
            VALUES (?, ?, ?, ?)
        """, (nome, email or None, data_nascimento, barbeiro_id))

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

    utilizador = utilizador_atual()

    historico = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, m.servico, m.estado, m.observacoes,
               m.barbeiro_id, u.nome AS barbeiro_nome
        FROM marcacoes m
        LEFT JOIN utilizadores u ON u.id = m.barbeiro_id
        WHERE m.cliente_id = ?
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




@app.route("/clientes/<int:cliente_id>/editar", methods=["POST"])
def cliente_editar(cliente_id):
    con = get_db()

    cliente = con.execute("""
        SELECT *
        FROM clientes
        WHERE id = ?
    """, (cliente_id,)).fetchone()

    if not cliente:
        con.close()
        return "Cliente não encontrado", 404

    if not pode_gerir_cliente(cliente):
        con.close()
        abort(403)

    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip()

    try:
        data_nascimento = normalizar_data_nascimento(
            request.form.get("data_nascimento", "")
        )
    except ValueError:
        con.close()
        return "Data de nascimento inválida", 400

    if not nome or not telefone:
        con.close()
        return "Nome e telefone são obrigatórios", 400

    numero_normalizado = normalizar_telefone(telefone)

    if not numero_normalizado:
        con.close()
        return "Número de telefone inválido", 400

    try:
        con.execute("""
            UPDATE clientes
            SET nome = ?,
                email = ?,
                data_nascimento = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            nome,
            email or None,
            data_nascimento,
            cliente_id,
        ))

        atual = con.execute("""
            SELECT id
            FROM telefones
            WHERE cliente_id = ?
              AND atual = 1
            ORDER BY id DESC
            LIMIT 1
        """, (cliente_id,)).fetchone()

        if atual:
            con.execute("""
                UPDATE telefones
                SET numero = ?,
                    numero_normalizado = ?
                WHERE id = ?
            """, (
                telefone,
                numero_normalizado,
                atual["id"],
            ))
        else:
            con.execute("""
                INSERT INTO telefones
                (cliente_id, numero, numero_normalizado, atual)
                VALUES (?, ?, ?, 1)
            """, (
                cliente_id,
                telefone,
                numero_normalizado,
            ))

        con.commit()

    except Exception:
        con.rollback()
        con.close()
        raise

    con.close()

    return redirect(url_for(
        "cliente_detalhe",
        cliente_id=cliente_id,
    ))


@app.route("/clientes/<int:cliente_id>/apagar", methods=["POST"])
def cliente_apagar(cliente_id):
    utilizador = utilizador_atual()
    if not utilizador or not (
        utilizador["e_admin"] or utilizador["papel"] == "gestor"
    ):
        abort(403)

    con = get_db()

    cliente = con.execute("""
        SELECT *
        FROM clientes
        WHERE id = ?
    """, (cliente_id,)).fetchone()

    if not cliente:
        con.close()
        return "Cliente não encontrado", 404

    if not pode_gerir_cliente(cliente):
        con.close()
        abort(403)

    try:
        # SMS relacionados com o cliente
        if con.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='sms_fila'
        """).fetchone():
            con.execute(
                "DELETE FROM sms_fila WHERE cliente_id = ?",
                (cliente_id,)
            )

        # Marcações
        con.execute(
            "DELETE FROM marcacoes WHERE cliente_id = ?",
            (cliente_id,)
        )

        # Telefones
        con.execute(
            "DELETE FROM telefones WHERE cliente_id = ?",
            (cliente_id,)
        )

        # Cliente
        con.execute(
            "DELETE FROM clientes WHERE id = ?",
            (cliente_id,)
        )

        con.commit()

    except Exception:
        con.rollback()
        con.close()
        raise

    con.close()

    return redirect(url_for("clientes"))



@app.route("/api/clientes/offline")
def clientes_sincronizacao_offline():
    utilizador = utilizador_atual()
    if not utilizador or not utilizador["ativo"]:
        return {"ok": False, "erro": "Sessão inválida."}, 401

    con = get_db()
    try:
        clientes = con.execute("""
            SELECT c.id, c.nome,
                COALESCE((
                    SELECT t.numero
                    FROM telefones t
                    WHERE t.cliente_id = c.id AND t.atual = 1
                    ORDER BY t.id DESC
                    LIMIT 1
                ), '') AS telefone
            FROM clientes c
            ORDER BY c.nome COLLATE NOCASE
        """).fetchall()

        resposta = jsonify({
            "ok": True,
            "clientes": [dict(c) for c in clientes]
        })
        resposta.headers["Cache-Control"] = "no-store"
        return resposta
    finally:
        con.close()


@app.route("/api/clientes/por-telefone")
def cliente_por_telefone():
    numero = normalizar_telefone(request.args.get("telefone", ""))
    if not numero:
        return {"ok": True, "encontrado": False}

    con = get_db()
    cliente = con.execute("""
        SELECT c.id, c.nome, c.email, c.data_nascimento, c.barbeiro_id, t.numero
        FROM telefones t
        JOIN clientes c ON c.id = t.cliente_id
        WHERE t.numero_normalizado = ? AND t.atual = 1
        ORDER BY t.id DESC
        LIMIT 1
    """, (numero,)).fetchone()
    if not cliente:
        con.close()
        return {"ok": True, "encontrado": False}

    resultado = dados_cliente_marcacao(con, cliente)
    con.close()
    return {"ok": True, "encontrado": True, "cliente": resultado}


def dados_cliente_marcacao(con, cliente):
    ultimas_visitas = con.execute("""
        SELECT inicio, estado
        FROM marcacoes
        WHERE cliente_id = ?
        ORDER BY inicio DESC
        LIMIT 3
    """, (cliente["id"],)).fetchall()
    return {
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
    }


@app.route("/api/clientes/por-nome")
def clientes_por_nome():
    def simplificar(valor):
        return "".join(c for c in unicodedata.normalize("NFD", valor or "").casefold()
                       if not unicodedata.combining(c))

    nome = request.args.get("nome", "").strip()
    if len(nome) < 2:
        return {"ok": True, "clientes": [], "mais_resultados": False}
    if len(nome) > 80:
        return {"ok": False, "erro": "Escreve até 80 caracteres."}, 400
    con = get_db()
    try:
        con.create_function("simplificar_nome", 1, simplificar)
        clientes = con.execute("""
            SELECT c.id, c.nome,
                (SELECT t.numero FROM telefones t WHERE t.cliente_id = c.id AND t.atual = 1
                 ORDER BY t.id DESC LIMIT 1) AS telefone
            FROM clientes c
            WHERE instr(simplificar_nome(c.nome), ?) > 0
            ORDER BY simplificar_nome(c.nome), c.id
            LIMIT 21
        """, (simplificar(nome),)).fetchall()
        return {"ok": True, "clientes": [dict(c) for c in clientes[:20]],
                "mais_resultados": len(clientes) > 20}
    finally:
        con.close()


@app.route("/api/clientes/<int:cliente_id>/marcacao")
def cliente_para_marcacao(cliente_id):
    con = get_db()
    try:
        cliente = con.execute("""
            SELECT c.*,
                (SELECT t.numero FROM telefones t WHERE t.cliente_id = c.id AND t.atual = 1
                 ORDER BY t.id DESC LIMIT 1) AS numero
            FROM clientes c WHERE c.id = ?
        """, (cliente_id,)).fetchone()
        if not cliente:
            return {"ok": False, "erro": "Cliente não encontrado."}, 404
        return {"ok": True, "encontrado": True, "cliente": dados_cliente_marcacao(con, cliente)}
    finally:
        con.close()


@app.route("/api/disponibilidade")
def disponibilidade():
    data_pedida = request.args.get("data", "").strip()
    hora_pedida = request.args.get("hora", "").strip()
    try:
        duracao = int(request.args.get("duracao", 30))
        duracoes_validas = range(15, 241, 15) if request.args.get("tipo") == "pessoal" else (15, 30, 45, 60, 90)
        if duracao not in duracoes_validas:
            raise ValueError
        inicio = datetime.fromisoformat(f"{data_pedida}T{hora_pedida}")
        if inicio.tzinfo is not None:
            raise ValueError
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
    periodos = conflitos_indisponibilidade(con, barbeiro_id, inicio, fim)
    con.close()

    conflitos = []
    for m in marcacoes:
        existente_inicio = datetime.fromisoformat(m["inicio"])
        existente_fim = existente_inicio + timedelta(minutes=m["duracao_minutos"])
        if inicio < existente_fim and fim > existente_inicio:
            conflitos.append({"id": m["id"], "nome": m["nome"] if barbeiro_permitido(barbeiro_id) else "Ocupado", "servico": m["servico"] if barbeiro_permitido(barbeiro_id) else "", "inicio": existente_inicio.strftime("%H:%M"), "fim": existente_fim.strftime("%H:%M")})

    for item in periodos:
        detalhes_permitidos = gestor() or barbeiro_id == utilizador["id"]
        conflitos.append({"id": item["id"], "tipo": item["tipo"],
            "nome": (({"encerramento": "Barbearia encerrada: ", "ausencia": "Ausência: ", "pessoal": "Pessoal: "}[item["tipo"]]) + item["motivo"]) if detalhes_permitidos else "Indisponível",
            "servico": "", "inicio": datetime.fromisoformat(item["inicio"]).strftime("%H:%M"),
            "fim": datetime.fromisoformat(item["fim"]).strftime("%H:%M")})

    return {"ok": True, "disponivel": len(conflitos) == 0, "data": inicio.date().isoformat(), "inicio": inicio.strftime("%H:%M"), "fim": fim.strftime("%H:%M"), "duracao": duracao, "conflitos": conflitos}


@app.route("/marcacoes/offline/sincronizar", methods=["POST"])
def sincronizar_marcacao_offline():
    """Sincroniza uma marcação criada sem rede no tablet.

    O destino nunca é aceite apenas por vir do browser: gestor/admin pode escolher
    qualquer profissional ativo; barbeiro normal só pode sincronizar para si próprio.
    O offline_id torna a operação idempotente para que um retry não duplique marcações.
    """
    utilizador = utilizador_atual()
    dados = request.get_json(silent=True) or {}
    offline_id = str(dados.get("offline_id", "")).strip()
    try:
        barbeiro_id = int(dados.get("barbeiro_id"))
    except (TypeError, ValueError):
        return {"ok": False, "erro": "Profissional inválido"}, 400

    if not offline_id or len(offline_id) > 100:
        return {"ok": False, "erro": "Identificador offline inválido"}, 400
    if not utilizador or not (
        utilizador["papel"] == "gestor"
        or utilizador["e_admin"]
        or utilizador["id"] == barbeiro_id
    ):
        return {"ok": False, "erro": "Sem permissão para esta agenda"}, 403

    con = get_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS marcacoes_offline_sync (
            offline_id TEXT PRIMARY KEY,
            utilizador_id INTEGER NOT NULL,
            barbeiro_id INTEGER NOT NULL,
            estado TEXT NOT NULL DEFAULT 'a_sincronizar',
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    existente = con.execute(
        "SELECT estado FROM marcacoes_offline_sync WHERE offline_id = ?",
        (offline_id,),
    ).fetchone()
    if existente and existente["estado"] == "sincronizada":
        con.close()
        return {"ok": True, "duplicada": True}

    if not existente:
        con.execute(
            "INSERT INTO marcacoes_offline_sync (offline_id, utilizador_id, barbeiro_id) VALUES (?, ?, ?)",
            (offline_id, utilizador["id"], barbeiro_id),
        )
        con.commit()
    con.close()

    # Reutiliza integralmente as validações e criação da marcação normal.
    campos = {
        "nome": dados.get("nome", ""),
        "telefone": dados.get("telefone", ""),
        "email": dados.get("email", ""),
        "cliente_id": dados.get("cliente_id", ""),
        "data_nascimento": dados.get("data_nascimento", ""),
        "observacoes": dados.get("observacoes", ""),
        "inicio": dados.get("inicio", ""),
        "duracao": str(dados.get("duracao", "30")),
        "repetir_semanalmente": str(dados.get("repetir_semanalmente", "0")),
        "repeticoes": str(dados.get("repeticoes", "1")),
    }

    agenda_anterior = session.get("agenda_aberta_id")
    session["agenda_aberta_id"] = barbeiro_id
    try:
        with app.test_request_context(
            "/marcacoes/nova",
            method="POST",
            data=campos,
            headers={"Cookie": request.headers.get("Cookie", "")},
        ):
            session["utilizador_id"] = utilizador["id"]
            session["agenda_aberta_id"] = barbeiro_id
            resposta = app.make_response(nova_marcacao())
    finally:
        if agenda_anterior is None:
            session.pop("agenda_aberta_id", None)
        else:
            session["agenda_aberta_id"] = agenda_anterior

    if 200 <= resposta.status_code < 400:
        con = get_db()
        con.execute(
            "UPDATE marcacoes_offline_sync SET estado = 'sincronizada' WHERE offline_id = ?",
            (offline_id,),
        )
        con.commit()
        con.close()
        return {"ok": True}

    con = get_db()
    con.execute("DELETE FROM marcacoes_offline_sync WHERE offline_id = ?", (offline_id,))
    con.commit()
    con.close()
    mensagem = resposta.get_data(as_text=True).strip() or "Não foi possível sincronizar"
    return {"ok": False, "erro": mensagem}, resposta.status_code


@app.route("/marcacoes/nova", methods=["POST"])
def nova_marcacao():
    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip()
    cliente_escolhido = request.form.get("cliente_id", "").strip()
    if cliente_escolhido:
        try:
            if not 0 < int(cliente_escolhido) <= 9223372036854775807:
                raise ValueError
            cliente_escolhido = str(int(cliente_escolhido))
        except ValueError:
            return "Cliente inválido", 400

    try:
        data_nascimento = normalizar_data_nascimento(
            request.form.get("data_nascimento", "")
        )
    except ValueError:
        return "Data de nascimento inválida", 400

    observacoes = request.form.get("observacoes", "").strip() or None
    utilizador = utilizador_atual()
    barbeiro_id = agenda_aberta_id()

    if not barbeiro_id:
        return "Abre primeiro a agenda individual do barbeiro onde queres fazer a marcação", 400
    if not pode_marcar_para(barbeiro_id):
        return "Sem permissão para esta agenda", 403
    inicio = request.form.get("inicio", "").strip()
    servico = ""
    repetir = request.form.get("repetir_semanalmente") == "1"
    try:
        duracao = int(request.form.get("duracao", 30))
        novo_inicio = datetime.fromisoformat(inicio)
        if novo_inicio.tzinfo is not None:
            raise ValueError
        repeticoes = int(request.form.get("repeticoes", 1)) if repetir else 1
    except (ValueError, TypeError):
        return "Data, hora ou duração inválida", 400

    if not nome or not telefone or not inicio or duracao not in (15, 30, 45, 60, 90):
        return "Dados obrigatórios em falta", 400

    if not 1 <= repeticoes <= 52:
        return "Número de marcações inválido (1 a 52)", 400
    if novo_inicio < datetime.now():
        return "Não é possível criar marcações no passado", 400
    inicios = [novo_inicio + timedelta(weeks=i) for i in range(repeticoes)]
    serie_id = secrets.token_hex(16) if repeticoes > 1 else None
    numero_normalizado = normalizar_telefone(telefone)
    if not numero_normalizado:
        return "Número de telefone inválido", 400

    con = get_db()
    concretizar_marcacoes_vencidas(con)

    sms_config = obter_sms_barbeiro(con, barbeiro_id)
    sms_ativo = sms_barbeiro_permitido(sms_config)

    email_config = obter_email_barbeiro(con, barbeiro_id)
    email_ativo = email_barbeiro_permitido(email_config)
    try:
        con.execute("BEGIN IMMEDIATE")
        if not con.execute("SELECT id FROM utilizadores WHERE id = ? AND ativo = 1", (barbeiro_id,)).fetchone():
            return "Barbeiro inválido", 400
        for inicio_item in inicios:
            fim_item = inicio_item + timedelta(minutes=duracao)
            if conflitos_indisponibilidade(con, barbeiro_id, inicio_item, fim_item):
                return f"Profissional indisponível em {inicio_item.strftime('%d/%m/%Y %H:%M')}. A série não foi criada.", 409
            conflitos = con.execute("""
                SELECT inicio, duracao_minutos FROM marcacoes
                WHERE estado != 'cancelada' AND barbeiro_id = ?
                UNION ALL
                SELECT inicio, duracao_minutos FROM reservas_online
                WHERE barbeiro_id = ? AND estado = 'aguarda_pagamento' AND expira_em > ?
            """, (barbeiro_id, barbeiro_id, datetime.now().astimezone().isoformat(timespec="seconds"))).fetchall()
            for m in conflitos:
                existente_inicio = datetime.fromisoformat(m["inicio"])
                existente_fim = existente_inicio + timedelta(minutes=m["duracao_minutos"])
                if inicio_item < existente_fim and fim_item > existente_inicio:
                    return f"Horário ocupado em {inicio_item.strftime('%d/%m/%Y %H:%M')}. A série não foi criada.", 409

        cur = con.cursor()
        if cliente_escolhido:
            escolhido = cur.execute("SELECT id, barbeiro_id FROM clientes WHERE id = ?", (int(cliente_escolhido),)).fetchone()
        cliente = cur.execute("""
            SELECT
                c.id,
                c.email,
                t.id AS telefone_id
            FROM telefones t
            JOIN clientes c ON c.id = t.cliente_id
            WHERE t.numero_normalizado = ? AND t.atual = 1
              AND (? = '' OR c.id = ?)
            ORDER BY t.id DESC
            LIMIT 1
        """, (numero_normalizado, cliente_escolhido, cliente_escolhido)).fetchone()
        if cliente_escolhido and not cliente:
            if cur.execute("SELECT 1 FROM telefones WHERE cliente_id = ? AND atual = 1", (int(cliente_escolhido),)).fetchone():
                return "O telefone do cliente escolhido mudou. Volta a procurar o cliente.", 409
            telefone_id = cur.execute("""
                INSERT INTO telefones (cliente_id, numero, numero_normalizado)
                VALUES (?, ?, ?)
            """, (int(cliente_escolhido), telefone, numero_normalizado)).lastrowid
            cliente = cur.execute("""
                SELECT c.id, c.email, t.id AS telefone_id
                FROM clientes c JOIN telefones t ON t.cliente_id = c.id
                WHERE c.id = ? AND t.id = ?
            """, (int(cliente_escolhido), telefone_id)).fetchone()

        if cliente:
            cliente_id = cliente["id"]

            email_cliente = (cliente["email"] or "").strip()
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
                INSERT INTO clientes (nome, email, data_nascimento, barbeiro_id)
                VALUES (?, ?, ?, ?)
            """, (nome, email or None, data_nascimento, barbeiro_id))
            cliente_id = cur.lastrowid
            cur.execute("""
                INSERT INTO telefones (cliente_id, numero, numero_normalizado)
                VALUES (?, ?, ?)
            """, (cliente_id, telefone, numero_normalizado))
            telefone_id = cur.lastrowid

        if not cliente:
            email_cliente = (email or "").strip()

        marcacao_ids = []
        for inicio_item in inicios:
            cur.execute("""
                INSERT INTO marcacoes
                (cliente_id, inicio, duracao_minutos, servico, observacoes, barbeiro_id, criado_por_id, serie_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (cliente_id, inicio_item.isoformat(timespec="minutes"), duracao, servico, observacoes, barbeiro_id, utilizador["id"], serie_id))
            marcacao_id = cur.lastrowid
            marcacao_ids.append(marcacao_id)

            # -------------------------------------------------
            # EMAIL — confirmação e lembretes por barbeiro
            # -------------------------------------------------
            if email_ativo and email_cliente:
                data_formatada_email = inicio_item.strftime("%d/%m/%Y")
                hora_formatada_email = inicio_item.strftime("%H:%M")

                barbeiro_nome = (
                    email_config["nome"]
                    if email_config
                    else ""
                )

                dados_modelo = {
                    "cliente": nome,
                    "barbeiro": barbeiro_nome,
                    "data": data_formatada_email,
                    "hora": hora_formatada_email,
                    "servico": servico or "",
                }

                # Confirmação
                if email_config["email_confirmacao"]:
                    modelo = renderizar_modelo_comunicacao(
                        con,
                        "email_confirmacao",
                        **dados_modelo
                    )

                    if modelo:
                        cur.execute("""
                            INSERT OR IGNORE INTO email_fila
                            (
                                cliente_id,
                                marcacao_id,
                                barbeiro_id,
                                email_destino,
                                tipo,
                                assunto,
                                mensagem,
                                estado,
                                previsto_para,
                                idempotency_key
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'pendente', ?, ?)
                        """, (
                            cliente_id,
                            marcacao_id,
                            barbeiro_id,
                            email_cliente,
                            "confirmacao",
                            modelo["assunto"] or "Marcação confirmada",
                            modelo["conteudo"],
                            datetime.now().isoformat(timespec="seconds"),
                            f"email_confirmacao:{marcacao_id}",
                        ))

                # Lembrete 24h
                if email_config["email_lembrete_24h"]:
                    previsto_email_24h = inicio_item - timedelta(hours=24)

                    if previsto_email_24h > datetime.now():
                        modelo = renderizar_modelo_comunicacao(
                            con,
                            "email_lembrete_24h",
                            **dados_modelo
                        )

                        if modelo:
                            cur.execute("""
                                INSERT OR IGNORE INTO email_fila
                                (
                                    cliente_id,
                                    marcacao_id,
                                    barbeiro_id,
                                    email_destino,
                                    tipo,
                                    assunto,
                                    mensagem,
                                    estado,
                                    previsto_para,
                                    idempotency_key
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, 'pendente', ?, ?)
                            """, (
                                cliente_id,
                                marcacao_id,
                                barbeiro_id,
                                email_cliente,
                                "lembrete_24h",
                                modelo["assunto"] or "Lembrete de marcação",
                                modelo["conteudo"],
                                previsto_email_24h.isoformat(timespec="seconds"),
                                f"email_lembrete_24h:{marcacao_id}",
                            ))

                # Lembrete 1h
                if email_config["email_lembrete_1h"]:
                    previsto_email_1h = inicio_item - timedelta(hours=1)

                    if previsto_email_1h > datetime.now():
                        modelo = renderizar_modelo_comunicacao(
                            con,
                            "email_lembrete_1h",
                            **dados_modelo
                        )

                        if modelo:
                            cur.execute("""
                                INSERT OR IGNORE INTO email_fila
                                (
                                    cliente_id,
                                    marcacao_id,
                                    barbeiro_id,
                                    email_destino,
                                    tipo,
                                    assunto,
                                    mensagem,
                                    estado,
                                    previsto_para,
                                    idempotency_key
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, 'pendente', ?, ?)
                            """, (
                                cliente_id,
                                marcacao_id,
                                barbeiro_id,
                                email_cliente,
                                "lembrete_1h",
                                modelo["assunto"] or "Lembrete de marcação",
                                modelo["conteudo"],
                                previsto_email_1h.isoformat(timespec="seconds"),
                                f"email_lembrete_1h:{marcacao_id}",
                            ))

            # -------------------------------------------------
            # SMS — exatamente 2 por marcação:
            #   1. confirmação imediata
            #   2. lembrete às 18:00 do dia anterior
            # -------------------------------------------------
            if sms_ativo:
                data_formatada = inicio_item.strftime("%d/%m/%Y")
                hora_formatada = inicio_item.strftime("%H:%M")

                barbeiro_nome_sms = (
                    sms_config["nome"]
                    if sms_config
                    else ""
                )

                dados_sms = {
                    "cliente": nome,
                    "data": data_formatada,
                    "hora": hora_formatada,
                    "barbeiro": barbeiro_nome_sms,
                    "servico": servico or "",
                }

                # Confirmação imediata
                modelo_confirmacao = renderizar_modelo_comunicacao(
                    con,
                    "sms_confirmacao",
                    **dados_sms
                )

                if modelo_confirmacao:
                    cur.execute("""
                        INSERT OR IGNORE INTO sms_fila
                        (
                            cliente_id,
                            telefone_id,
                            marcacao_id,
                            telefone_destino,
                            tipo,
                            mensagem,
                            previsto_para,
                            idempotency_key
                        )
                        VALUES (?, ?, ?, ?, 'confirmacao', ?, ?, ?)
                    """, (
                        cliente_id,
                        telefone_id,
                        marcacao_id,
                        telefone,
                        modelo_confirmacao["conteudo"],
                        datetime.now().isoformat(timespec="seconds"),
                        f"confirmacao:{marcacao_id}",
                    ))

                # Lembrete às 18:00 do dia anterior
                previsto_para = datetime.combine(
                    inicio_item.date() - timedelta(days=1),
                    datetime.strptime("18:00", "%H:%M").time()
                )

                if previsto_para > datetime.now():
                    modelo_lembrete = renderizar_modelo_comunicacao(
                        con,
                        "sms_lembrete_24h",
                        **dados_sms
                    )

                    if modelo_lembrete:
                        cur.execute("""
                            INSERT OR IGNORE INTO sms_fila
                            (
                                cliente_id,
                                telefone_id,
                                marcacao_id,
                                telefone_destino,
                                tipo,
                                mensagem,
                                previsto_para,
                                idempotency_key
                            )
                            VALUES (?, ?, ?, ?, 'lembrete_dia_anterior', ?, ?, ?)
                        """, (
                            cliente_id,
                            telefone_id,
                            marcacao_id,
                            telefone,
                            modelo_lembrete["conteudo"],
                            previsto_para.isoformat(timespec="seconds"),
                            f"lembrete_dia_anterior:{marcacao_id}",
                        ))

        con.commit()
        g.atividade_extra = {
            "acao": "criou_serie_marcacoes" if len(marcacao_ids) > 1 else "criou_marcacao",
            "alvo_barbeiro_id": barbeiro_id,
            "alvo_barbeiro_nome": email_config["nome"] if email_config else "",
            "marcacao_id": marcacao_ids[0] if marcacao_ids else None,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    data_formatada = novo_inicio.strftime("%d/%m/%Y")
    hora_formatada = novo_inicio.strftime("%H:%M")

    if sms_ativo and not serie_id:
        con_sms = get_db()

        modelo_sms = renderizar_modelo_comunicacao(
            con_sms,
            "sms_confirmacao",
            cliente=nome,
            data=data_formatada,
            hora=hora_formatada,
            barbeiro=(email_config["nome"] if email_config else ""),
            servico=servico or "",
        )

        con_sms.close()

        if modelo_sms:
            enviar_sms_do_barbeiro(
                barbeiro_id,
                telefone,
                modelo_sms["conteudo"],
            )

    # Reabrir a agenda do profissional que recebeu a marcação, em vez da
    # agenda pessoal do utilizador que a criou.
    return redirect(url_for(
        "semana", data=novo_inicio.date().isoformat(), barbeiro=barbeiro_id
    ))

def guardar_bloqueio_pessoal(bloqueio_id=None):
    utilizador = utilizador_atual()
    descricao = request.form.get("descricao", "").strip()
    try:
        inicio = datetime.fromisoformat(request.form.get("inicio", ""))
        duracao = int(request.form.get("duracao", 60))
        if inicio.tzinfo is not None or inicio.second or inicio.microsecond or duracao not in range(15, 241, 15) or not descricao:
            raise ValueError
    except (TypeError, ValueError):
        return {"ok": False, "erro": "Indica descrição, início e duração válidos."}, 400
    con = get_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        if bloqueio_id is not None:
            bloqueio = con.execute("SELECT * FROM bloqueios_pessoais WHERE id = ?", (bloqueio_id,)).fetchone()
            if not bloqueio:
                return {"ok": False, "erro": "Compromisso não encontrado."}, 404
            barbeiro_id = bloqueio["barbeiro_id"]
        else:
            barbeiro_id = request.form.get("barbeiro_id", type=int) or utilizador["id"]
        if not gestor() and barbeiro_id != utilizador["id"]:
            return {"ok": False, "erro": "Só podes gerir os teus compromissos."}, 403
        if not con.execute("SELECT id FROM utilizadores WHERE id = ? AND ativo = 1 AND COALESCE(e_admin,0) = 0", (barbeiro_id,)).fetchone():
            return {"ok": False, "erro": "Escolhe um profissional ativo."}, 400
        fim = inicio + timedelta(minutes=duracao)
        if conflitos_indisponibilidade(con, barbeiro_id, inicio, fim, ignorar_bloqueio_id=bloqueio_id):
            return {"ok": False, "erro": "Este período já está ocupado por um compromisso, ausência ou encerramento."}, 409
        candidatos = con.execute("""
            SELECT inicio, duracao_minutos FROM marcacoes WHERE barbeiro_id = ? AND estado != 'cancelada'
            UNION ALL
            SELECT inicio, duracao_minutos FROM reservas_online
            WHERE barbeiro_id = ? AND estado = 'aguarda_pagamento' AND expira_em > ?
        """, (barbeiro_id, barbeiro_id, datetime.now().astimezone().isoformat(timespec="seconds"))).fetchall()
        for item in candidatos:
            item_inicio = datetime.fromisoformat(item["inicio"])
            if inicio < item_inicio + timedelta(minutes=item["duracao_minutos"]) and fim > item_inicio:
                return {"ok": False, "erro": "Existem marcações ou reservas neste horário."}, 409
        if bloqueio_id is None:
            cur = con.execute("""INSERT INTO bloqueios_pessoais
                (inicio, duracao_minutos, descricao, barbeiro_id, criado_por_id) VALUES (?, ?, ?, ?, ?)
            """, (inicio.isoformat(timespec="minutes"), duracao, descricao, barbeiro_id, utilizador["id"]))
            bloqueio_id = cur.lastrowid
            status = 201
        else:
            con.execute("""UPDATE bloqueios_pessoais SET inicio = ?, duracao_minutos = ?, descricao = ?,
                atualizado_em = CURRENT_TIMESTAMP WHERE id = ?
            """, (inicio.isoformat(timespec="minutes"), duracao, descricao, bloqueio_id))
            status = 200
        con.commit()
        return {"ok": True, "id": bloqueio_id, "data": inicio.date().isoformat(), "barbeiro_id": barbeiro_id}, status
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@app.route("/bloqueios/novo", methods=["POST"])
def novo_bloqueio_pessoal():
    return guardar_bloqueio_pessoal()


@app.route("/bloqueios/<int:bloqueio_id>/editar", methods=["POST"])
def editar_bloqueio_pessoal(bloqueio_id):
    return guardar_bloqueio_pessoal(bloqueio_id)


@app.route("/bloqueios/<int:bloqueio_id>/eliminar", methods=["POST"])
def eliminar_bloqueio_pessoal(bloqueio_id):
    con = get_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        item = con.execute("SELECT * FROM bloqueios_pessoais WHERE id = ?", (bloqueio_id,)).fetchone()
        if not item:
            return {"ok": False, "erro": "Compromisso não encontrado."}, 404
        if not gestor() and item["barbeiro_id"] != utilizador_atual()["id"]:
            return {"ok": False, "erro": "Só podes eliminar os teus compromissos."}, 403
        con.execute("DELETE FROM bloqueios_pessoais WHERE id = ?", (bloqueio_id,))
        con.commit()
        return {"ok": True}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@app.route("/indisponibilidades/nova", methods=["POST"])
def nova_indisponibilidade():
    tipo = request.form.get("tipo", "").strip()
    motivo = request.form.get("motivo", "").strip()
    utilizador = utilizador_atual()
    barbeiro_id = request.form.get("barbeiro_id", type=int)
    if tipo not in {"ausencia", "encerramento"} or not motivo:
        return {"ok": False, "erro": "Indica o tipo e o motivo.", "nada_alterado": True}, 400
    if tipo == "encerramento":
        if not gestor():
            return {"ok": False, "erro": "Só o gestor ou Admin pode encerrar a barbearia.", "nada_alterado": True}, 403
        barbeiro_id = None
    else:
        barbeiro_id = barbeiro_id or utilizador["id"]
        if not gestor() and barbeiro_id != utilizador["id"]:
            return {"ok": False, "erro": "Só podes gerir as tuas ausências.", "nada_alterado": True}, 403
    try:
        inicio = datetime.fromisoformat(request.form.get("inicio", ""))
        fim = datetime.fromisoformat(request.form.get("fim", ""))
        if any(item.tzinfo is not None or item.second or item.microsecond for item in (inicio, fim)) or fim <= inicio:
            raise ValueError
    except (ValueError, TypeError):
        return {"ok": False, "erro": "Indica um período válido, com fim posterior ao início.", "nada_alterado": True}, 400

    con = get_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        if barbeiro_id is not None and not con.execute("SELECT id FROM utilizadores WHERE id = ? AND ativo = 1 AND COALESCE(e_admin,0) = 0", (barbeiro_id,)).fetchone():
            return {"ok": False, "erro": "Escolhe um profissional ativo.", "nada_alterado": True}, 400
        # No bookings or reservations are cancelled/moved as a side effect.
        candidatos = con.execute("""
            SELECT m.id, m.inicio, m.duracao_minutos, c.nome, m.barbeiro_id, 'marcacao' AS origem
            FROM marcacoes m JOIN clientes c ON c.id = m.cliente_id
            WHERE m.estado != 'cancelada' AND (? IS NULL OR m.barbeiro_id = ?)
            UNION ALL
            SELECT r.id, r.inicio, r.duracao_minutos, 'Reserva online', r.barbeiro_id, 'reserva'
            FROM reservas_online r WHERE r.estado = 'aguarda_pagamento' AND r.expira_em > ?
              AND (? IS NULL OR r.barbeiro_id = ?)
            UNION ALL
            SELECT b.id, b.inicio, b.duracao_minutos, b.descricao, b.barbeiro_id, 'pessoal'
            FROM bloqueios_pessoais b WHERE (? IS NULL OR b.barbeiro_id = ?)
        """, (barbeiro_id, barbeiro_id, datetime.now().astimezone().isoformat(timespec="seconds"), barbeiro_id, barbeiro_id, barbeiro_id, barbeiro_id)).fetchall()
        conflitos = []
        for item in candidatos:
            item_inicio = datetime.fromisoformat(item["inicio"])
            item_fim = item_inicio + timedelta(minutes=item["duracao_minutos"])
            if inicio < item_fim and fim > item_inicio:
                conflitos.append({"id": item["id"], "tipo": item["origem"], "nome": item["nome"],
                    "data": item_inicio.strftime("%d/%m/%Y"), "inicio": item_inicio.strftime("%H:%M"),
                    "fim": item_fim.strftime("%H:%M"), "barbeiro_id": item["barbeiro_id"]})
        if conflitos:
            return {"ok": False, "erro": "Existem marcações ou reservas neste período. Resolve-as antes de criar o período.",
                    "conflitos": conflitos, "nada_alterado": True}, 409
        existente = con.execute("""
            SELECT id FROM indisponibilidades WHERE inicio < ? AND fim > ?
              AND (? IS NULL OR tipo = 'encerramento' OR barbeiro_id = ?)
        """, (fim.isoformat(timespec="minutes"), inicio.isoformat(timespec="minutes"), barbeiro_id, barbeiro_id)).fetchone()
        if existente:
            return {"ok": False, "erro": "Já existe uma ausência ou encerramento que abrange este período.", "nada_alterado": True}, 409
        cur = con.execute("""
            INSERT INTO indisponibilidades (tipo, inicio, fim, motivo, barbeiro_id, criado_por_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tipo, inicio.isoformat(timespec="minutes"), fim.isoformat(timespec="minutes"), motivo, barbeiro_id, utilizador["id"]))
        con.commit()
        return {"ok": True, "id": cur.lastrowid, "tipo": tipo, "data": inicio.date().isoformat(), "barbeiro_id": barbeiro_id}, 201
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@app.route("/indisponibilidades/<int:indisponibilidade_id>/eliminar", methods=["POST"])
def eliminar_indisponibilidade(indisponibilidade_id):
    con = get_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        item = con.execute("SELECT * FROM indisponibilidades WHERE id = ?", (indisponibilidade_id,)).fetchone()
        if not item:
            return {"ok": False, "erro": "Período não encontrado."}, 404
        if not pode_gerir_indisponibilidade(item):
            return {"ok": False, "erro": "Sem permissão para eliminar este período."}, 403
        con.execute("DELETE FROM indisponibilidades WHERE id = ?", (indisponibilidade_id,))
        con.commit()
        return {"ok": True, "id": indisponibilidade_id}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@app.route("/marcacoes/<int:marcacao_id>/cancelar-serie-futura", methods=["POST"])
def cancelar_serie_futura(marcacao_id):
    con = get_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        marcacao = con.execute("SELECT * FROM marcacoes WHERE id = ?", (marcacao_id,)).fetchone()
        if not marcacao:
            return "Marcação não encontrada", 404
        if not pode_alterar_marcacao(marcacao):
            return "Sem permissão para esta marcação", 403
        if not marcacao["serie_id"]:
            return "Esta marcação não pertence a uma série", 400
        limite = max(marcacao["inicio"], datetime.now().isoformat(timespec="seconds"))
        futuras = con.execute("""
            SELECT * FROM marcacoes WHERE serie_id = ? AND barbeiro_id = ?
            AND inicio >= ? AND estado = 'marcada'
        """, (marcacao["serie_id"], marcacao["barbeiro_id"], limite)).fetchall()
        if any(not pode_alterar_marcacao(item) for item in futuras):
            return "Sem permissão para esta série", 403
        ids = [item["id"] for item in futuras]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            con.execute(f"UPDATE marcacoes SET estado = 'cancelada', atualizado_em = CURRENT_TIMESTAMP WHERE id IN ({placeholders})", ids)
            con.execute(f"""
                UPDATE sms_fila SET estado = 'cancelado', erro = 'Série cancelada', ultima_tentativa_em = ?
                WHERE marcacao_id IN ({placeholders}) AND estado = 'pendente' AND tipo != 'confirmacao_serie'
            """, [datetime.now().isoformat(timespec="seconds"), *ids])
            con.execute(f"UPDATE email_fila SET estado = 'cancelado' WHERE marcacao_id IN ({placeholders}) AND estado = 'pendente'", ids)
            restantes = con.execute("SELECT 1 FROM marcacoes WHERE serie_id = ? AND barbeiro_id = ? AND estado = 'marcada' AND inicio >= ?", (marcacao["serie_id"], marcacao["barbeiro_id"], datetime.now().isoformat(timespec="seconds"))).fetchone()
            if not restantes:
                con.execute("""UPDATE sms_fila SET estado = 'cancelado', erro = 'Série cancelada'
                    WHERE tipo = 'confirmacao_serie' AND estado = 'pendente'
                    AND marcacao_id IN (SELECT id FROM marcacoes WHERE serie_id = ? AND barbeiro_id = ?)
                """, (marcacao["serie_id"], marcacao["barbeiro_id"]))
        con.commit()
        return redirect(url_for("semana", data=marcacao["inicio"][:10], barbeiro=marcacao["barbeiro_id"]))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


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
    con.execute("BEGIN IMMEDIATE")

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
    if conflitos_indisponibilidade(con, marcacao["barbeiro_id"], novo_inicio, novo_fim):
        con.close()
        return {"ok": False, "erro": "A duração invade um período pessoal, ausência ou encerramento."}, 409

    conflitos_db = con.execute("""
        SELECT m.id, m.inicio, m.duracao_minutos, c.nome
        FROM marcacoes m
        JOIN clientes c ON c.id = m.cliente_id
        WHERE substr(m.inicio, 1, 10) = ?
          AND m.id != ?
          AND m.estado != 'cancelada'
          AND m.barbeiro_id = ?
        ORDER BY m.inicio
    """, (
        novo_inicio.date().isoformat(),
        marcacao_id,
        marcacao["barbeiro_id"],
    )).fetchall()

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

@app.route("/marcacoes/<int:marcacao_id>/fecho", methods=["POST"])
def fechar_marcacao(marcacao_id):
    resultado = request.form.get("resultado", "").strip()
    if resultado not in {"recebido", "faltou", "desmarcou"}:
        return "Resultado inválido", 400

    valor_centimos = None
    metodo_pagamento = None
    if resultado == "recebido":
        metodo_pagamento = request.form.get("metodo_pagamento", "").strip().lower()
        if metodo_pagamento not in ("mbway", "cash"):
            return "Escolhe MB WAY ou Cash", 400
        valor_texto = request.form.get("valor", "").strip().replace(",", ".")
        try:
            valor = float(valor_texto)
        except ValueError:
            return "Valor inválido", 400
        if valor < 0 or valor > 10000:
            return "Valor inválido", 400
        valor_centimos = round(valor * 100)

    con = get_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        marcacao = con.execute(
            "SELECT id, cliente_id, inicio, duracao_minutos, barbeiro_id, criado_por_id, valor_cobrado_centimos FROM marcacoes WHERE id = ?",
            (marcacao_id,),
        ).fetchone()
        if not marcacao:
            return "Marcação não encontrada", 404
        utilizador = utilizador_atual()

        pode_gerir_financeiro = bool(
            utilizador
            and (
                utilizador["e_admin"]
                or utilizador["papel"] == "gestor"
                or marcacao["barbeiro_id"] == utilizador["id"]
            )
        )

        if not pode_gerir_financeiro:
            return "Sem permissão para consultar ou alterar valores desta marcação", 403

        if resultado == "recebido" and marcacao["valor_cobrado_centimos"] is not None:
            return "Esta marcação já foi fechada com valor e não pode ser alterada novamente", 409

        estado = "concluída" if resultado == "recebido" else ("faltou" if resultado == "faltou" else "cancelada")
        con.execute(
            """
            UPDATE marcacoes
            SET estado = ?, valor_cobrado_centimos = ?,
                metodo_pagamento = ?,
                fechado_em = ?, fechado_por_id = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (estado, valor_centimos, metodo_pagamento, agora_barbearia().isoformat(timespec="seconds"), utilizador["id"], marcacao_id),
        )
        con.commit()

        barbeiro = con.execute("SELECT nome FROM utilizadores WHERE id = ?", (marcacao["barbeiro_id"],)).fetchone()
        g.atividade_extra = {
            "acao": "fecho_recebido" if resultado == "recebido" else f"fecho_{resultado}",
            "alvo_barbeiro_id": marcacao["barbeiro_id"],
            "alvo_barbeiro_nome": barbeiro["nome"] if barbeiro else "",
            "marcacao_id": marcacao_id,
        }
        return redirect(url_for("semana", data=marcacao["inicio"][:10], barbeiro=marcacao["barbeiro_id"]))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@app.route("/marcacoes/<int:marcacao_id>/estado", methods=["POST"])
def alterar_estado_marcacao(marcacao_id):
    estado = request.form.get("estado", "").strip()
    estados_validos = {"marcada", "concluída", "cancelada", "faltou"}
    if estado not in estados_validos:
        return "Estado inválido", 400

    con = get_db()
    concretizar_marcacoes_vencidas(con)
    con.execute("BEGIN IMMEDIATE")
    marcacao = con.execute("""
        SELECT
            m.id,
            m.cliente_id,
            m.inicio,
            m.duracao_minutos,
            m.barbeiro_id,
            m.criado_por_id,
            c.nome AS cliente_nome,
            u.nome AS barbeiro_nome,
            t.id AS telefone_id,
            t.numero AS telefone
        FROM marcacoes m
        JOIN clientes c ON c.id = m.cliente_id
        JOIN utilizadores u ON u.id = m.barbeiro_id
        LEFT JOIN telefones t
          ON t.cliente_id = m.cliente_id
         AND t.atual = 1
        WHERE m.id = ?
        ORDER BY t.id DESC
        LIMIT 1
    """, (marcacao_id,)).fetchone()
    if not marcacao:
        con.close()
        return "Marcação não encontrada", 404
    if not pode_alterar_marcacao(marcacao):
        con.close()
        return "Sem permissão para esta marcação", 403

    if estado == "marcada":
        inicio_m = datetime.fromisoformat(marcacao["inicio"])
        if conflitos_indisponibilidade(con, marcacao["barbeiro_id"], inicio_m, inicio_m + timedelta(minutes=marcacao["duracao_minutos"])):
            con.close()
            return "Profissional indisponível neste horário", 409

    enviar_sms_cancelamento = (
        estado == "cancelada"
        and request.form.get("enviar_sms_cancelamento") == "1"
    )

    texto_sms_cancelamento = (
        request.form.get("sms_cancelamento_texto", "").strip()
        if enviar_sms_cancelamento
        else ""
    )

    if enviar_sms_cancelamento:
        sms_config = obter_sms_barbeiro(con, marcacao["barbeiro_id"])

        if not sms_barbeiro_permitido(sms_config):
            con.close()
            return "SMS não está ativo para este profissional", 400

        if not marcacao["telefone_id"] or not marcacao["telefone"]:
            con.close()
            return "O cliente não tem telefone disponível para SMS", 400

        if not texto_sms_cancelamento:
            con.close()
            return "O texto do SMS de cancelamento está vazio", 400

    if estado in {"marcada", "cancelada", "faltou"}:
        con.execute(
            """
            UPDATE marcacoes
            SET estado = ?,
                valor_cobrado_centimos = NULL,
                metodo_pagamento = NULL,
                fechado_em = NULL,
                fechado_por_id = NULL,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (estado, marcacao_id),
        )
    else:
        con.execute(
            """
            UPDATE marcacoes
            SET estado = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (estado, marcacao_id),
        )

    if estado == "cancelada":
        agora = datetime.now().isoformat(timespec="seconds")

        con.execute("""
            UPDATE sms_fila
            SET estado = 'cancelado',
                erro = 'Marcação cancelada',
                ultima_tentativa_em = ?
            WHERE marcacao_id = ?
              AND estado = 'pendente'
        """, (agora, marcacao_id))

        con.execute("""
            UPDATE email_fila
            SET estado = 'cancelado'
            WHERE marcacao_id = ?
              AND estado = 'pendente'
        """, (marcacao_id,))

        if enviar_sms_cancelamento:
            con.execute("""
                INSERT OR IGNORE INTO sms_fila
                (
                    cliente_id,
                    telefone_id,
                    marcacao_id,
                    telefone_destino,
                    tipo,
                    mensagem,
                    estado,
                    previsto_para,
                    idempotency_key
                )
                VALUES (?, ?, ?, ?, 'cancelamento', ?, 'pendente', ?, ?)
            """, (
                marcacao["cliente_id"],
                marcacao["telefone_id"],
                marcacao_id,
                marcacao["telefone"],
                texto_sms_cancelamento,
                agora,
                f"cancelamento:{marcacao_id}",
            ))

    con.commit()
    data_marcacao = marcacao["inicio"][:10]
    con.close()

    return redirect(url_for("semana", data=data_marcacao))


garantir_esquema()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
