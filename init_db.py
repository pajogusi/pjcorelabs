import sqlite3
from pathlib import Path

DB = Path(__file__).with_name("blessed.db")

con = sqlite3.connect(DB)
con.execute("PRAGMA foreign_keys = ON")

con.executescript("""
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    data_nascimento TEXT,
    email TEXT,

    permite_sms_marcacoes INTEGER NOT NULL DEFAULT 0
        CHECK (permite_sms_marcacoes IN (0, 1)),
    sms_consentimento_em TEXT,

    permite_email_comunicacoes INTEGER NOT NULL DEFAULT 0
        CHECK (permite_email_comunicacoes IN (0, 1)),
    email_consentimento_em TEXT,

    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telefones (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    numero TEXT NOT NULL,
    numero_normalizado TEXT NOT NULL,
    atual INTEGER NOT NULL DEFAULT 1
        CHECK (atual IN (0, 1)),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    terminado_em TEXT,

    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE INDEX IF NOT EXISTS idx_telefones_numero
ON telefones(numero_normalizado);

CREATE INDEX IF NOT EXISTS idx_telefones_cliente
ON telefones(cliente_id);
""")

con.executescript("""
CREATE TABLE IF NOT EXISTS marcacoes (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    inicio TEXT NOT NULL,
    duracao_minutos INTEGER NOT NULL
        CHECK (duracao_minutos > 0),
    servico TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'marcada'
        CHECK (estado IN (
            'marcada',
            'concluída',
            'cancelada',
            'faltou'
        )),
    origem TEXT NOT NULL DEFAULT 'barbearia'
        CHECK (origem IN ('barbearia', 'online')),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE INDEX IF NOT EXISTS idx_marcacoes_inicio
ON marcacoes(inicio);

CREATE INDEX IF NOT EXISTS idx_marcacoes_cliente
ON marcacoes(cliente_id);
""")

con.executescript("""
CREATE TABLE IF NOT EXISTS campanhas (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    canal TEXT NOT NULL DEFAULT 'email'
        CHECK (canal IN ('email', 'sms')),
    tipo TEXT NOT NULL DEFAULT 'geral'
        CHECK (tipo IN (
            'geral',
            'aniversário',
            'natal',
            'ano_novo',
            'ferias',
            'horario_especial'
        )),
    estado TEXT NOT NULL DEFAULT 'rascunho'
        CHECK (estado IN (
            'rascunho',
            'agendada',
            'em_envio',
            'pausada',
            'concluida',
            'cancelada'
        )),
    envio_previsto TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
""")

con.executescript("""
CREATE TABLE IF NOT EXISTS sms_fila (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    telefone_id INTEGER NOT NULL,
    marcacao_id INTEGER,
    campanha_id INTEGER,

    telefone_destino TEXT NOT NULL,
    tipo TEXT NOT NULL,
    mensagem TEXT NOT NULL,

    prioridade INTEGER NOT NULL DEFAULT 100,
    valido_ate TEXT,

    estado TEXT NOT NULL DEFAULT 'pendente'
        CHECK (estado IN (
            'pendente',
            'a_enviar',
            'enviado',
            'entregue',
            'falhou',
            'cancelado'
        )),

    tentativas INTEGER NOT NULL DEFAULT 0,
    previsto_para TEXT,

    provider TEXT,
    provider_message_id TEXT,
    idempotency_key TEXT UNIQUE,

    aceite_provider_em TEXT,
    enviado_em TEXT,
    entregue_em TEXT,
    ultima_tentativa_em TEXT,

    erro TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (telefone_id) REFERENCES telefones(id),
    FOREIGN KEY (marcacao_id) REFERENCES marcacoes(id),
    FOREIGN KEY (campanha_id) REFERENCES campanhas(id)
);

CREATE INDEX IF NOT EXISTS idx_sms_estado
ON sms_fila(estado);

CREATE INDEX IF NOT EXISTS idx_sms_previsto
ON sms_fila(previsto_para);

CREATE INDEX IF NOT EXISTS idx_sms_cliente
ON sms_fila(cliente_id);

CREATE INDEX IF NOT EXISTS idx_sms_campanha
ON sms_fila(campanha_id);

CREATE INDEX IF NOT EXISTS idx_sms_prioridade
ON sms_fila(prioridade);
""")

con.commit()
con.close()

print(f"Base de dados criada: {DB}")
