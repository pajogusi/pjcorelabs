#!/usr/bin/env python3
"""Series tests use synthetic SQLite data and mocked delivery, never production."""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent


class SeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='multiuser-series-')
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'series.db'
        with closing(sqlite3.connect(self.db)) as con, con:
            con.executescript('''
                CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, email TEXT,
                    data_nascimento TEXT, alerta_inatividade_visto_em TEXT, atualizado_em TEXT);
                CREATE TABLE telefones (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL,
                    numero TEXT NOT NULL, numero_normalizado TEXT NOT NULL, atual INTEGER DEFAULT 1);
                CREATE TABLE marcacoes (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL,
                    inicio TEXT NOT NULL, duracao_minutos INTEGER NOT NULL,
                    servico TEXT NOT NULL DEFAULT '', estado TEXT DEFAULT 'marcada', atualizado_em TEXT);
            ''')
        spec = importlib.util.spec_from_file_location('series_app', BASE / 'app.py')
        self.mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'BLESSED_DB': str(self.db), 'BLESSED_DISABLE_SMS': '1'}):
            spec.loader.exec_module(self.mod)
        self.mod.app.config.update(TESTING=True, SECRET_KEY='series-test')
        self.sms = []
        self.mod.enviar_sms_smsgate = lambda phone, text: self.sms.append((phone, text)) or True
        with closing(self.mod.get_db()) as con, con:
            for uid, role, admin in [(1, 'gestor', 0), (2, 'barbeiro', 0), (3, 'barbeiro', 0), (4, 'barbeiro', 1)]:
                con.execute('''INSERT INTO utilizadores
                    (id,nome,username,password_hash,papel,e_admin,sms_autorizado,sms_provider)
                    VALUES (?,?,?,?,?,?,1,'smsgate')''', (uid, f'B{uid}', f'b{uid}', 'unused', role, admin))
        self.client = self.client_for(2)
        self.start = (datetime.now() + timedelta(days=30)).replace(hour=10, minute=0, second=0, microsecond=0)

    def client_for(self, uid):
        client = self.mod.app.test_client()
        with client.session_transaction() as session:
            session['utilizador_id'] = uid
        return client

    def create(self, client=None, **changes):
        data = dict(nome='Cliente de teste', telefone='+351910111222', inicio=self.start.isoformat(timespec='minutes'),
                    duracao='30', barbeiro_id='2', repetir_semanalmente='1', repeticoes='4')
        data.update(changes)
        return (client or self.client).post('/marcacoes/nova', data=data)

    def rows(self, sql, args=()):
        con = self.mod.get_db()
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def worker(self):
        spec = importlib.util.spec_from_file_location('series_sms_worker', BASE / 'email_worker.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'app': self.mod}):
            spec.loader.exec_module(module)
        module.processar_fila()

    def test_weekly_dates_owner_and_single_confirmation(self):
        self.assertEqual(self.create().status_code, 302)
        rows = self.rows('SELECT * FROM marcacoes ORDER BY inicio')
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r['serie_id'] for r in rows}), 1)
        self.assertTrue(rows[0]['serie_id'])
        for i, r in enumerate(rows):
            self.assertEqual(datetime.fromisoformat(r['inicio']), self.start + timedelta(weeks=i))
            self.assertEqual((r['barbeiro_id'], r['criado_por_id']), (2, 2))
        confirmations = self.rows("SELECT * FROM sms_fila WHERE tipo='confirmacao_serie'")
        self.assertEqual(len(confirmations), 1)
        for r in rows:
            self.assertIn(datetime.fromisoformat(r['inicio']).strftime('%d/%m/%Y'), confirmations[0]['mensagem'])
        self.assertEqual(len(self.rows("SELECT * FROM sms_fila WHERE tipo='lembrete_dia_anterior'")), 4)
        self.assertEqual(len(self.rows("SELECT * FROM sms_fila WHERE tipo='lembrete_1h'")), 4)
        self.assertEqual(self.sms, [])
        self.worker()
        self.worker()
        self.assertEqual(len(self.sms), 1)

    def test_conflict_later_date_rolls_back_everything(self):
        self.assertEqual(self.create(repetir_semanalmente='0', inicio=(self.start+timedelta(weeks=2)).isoformat(timespec='minutes')).status_code, 302)
        before = [tuple(r) for r in self.rows('SELECT * FROM clientes')]
        self.assertEqual(self.create(nome='Nome alterado').status_code, 409)
        self.assertEqual(len(self.rows('SELECT * FROM marcacoes')), 1)
        self.assertEqual(before, [tuple(r) for r in self.rows('SELECT * FROM clientes')])
        self.assertEqual(self.rows("SELECT * FROM sms_fila WHERE tipo='confirmacao_serie'"), [])

    def test_other_barber_same_times_are_allowed(self):
        self.assertEqual(self.create().status_code, 302)
        self.assertEqual(self.create(client=self.client_for(3), barbeiro_id='3', telefone='+351910333444').status_code, 302)
        self.assertEqual(len(self.rows('SELECT * FROM marcacoes')), 8)

    def test_barber_cannot_reuse_other_barbers_client(self):
        self.create(client=self.client_for(3), barbeiro_id='3')
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(len(self.rows('SELECT * FROM marcacoes')), 4)

    def test_manager_and_admin_choose_target_barber(self):
        for uid, offset in [(1, 0), (4, 1)]:
            r = self.create(client=self.client_for(uid), barbeiro_id='3', inicio=(self.start+timedelta(days=offset)).isoformat(timespec='minutes'))
            self.assertEqual(r.status_code, 302)
            self.assertIn('barbeiro=3', r.location)
            self.assertEqual(len(self.rows('SELECT * FROM marcacoes WHERE criado_por_id=? AND barbeiro_id=3', (uid,))), 4)

    def test_tampered_target_stays_in_own_agenda(self):
        self.assertEqual(self.create(barbeiro_id='3').status_code, 302)
        self.assertEqual({r['barbeiro_id'] for r in self.rows('SELECT * FROM marcacoes')}, {2})

    def test_invalid_counts_dates_and_inactive_target(self):
        for value in ['0', '-1', '53', 'abc']:
            self.assertEqual(self.create(repeticoes=value).status_code, 400)
        for value in ['bad', '2000-01-01T10:00', '2030-01-01T10:00+00:00']:
            self.assertEqual(self.create(inicio=value).status_code, 400)
        self.assertEqual(self.create(client=self.client_for(1), barbeiro_id='999').status_code, 400)
        self.assertEqual(self.rows('SELECT * FROM marcacoes'), [])

    def test_single_booking_keeps_single_behaviour(self):
        self.assertEqual(self.create(repetir_semanalmente='0', repeticoes='bad').status_code, 302)
        row = self.rows('SELECT * FROM marcacoes')[0]
        self.assertIsNone(row['serie_id'])
        self.assertEqual(len(self.sms), 1)
        self.assertEqual(self.client.post(f"/marcacoes/{row['id']}/cancelar-serie-futura").status_code, 400)

    def test_cancel_from_middle_preserves_earlier_and_other_series(self):
        self.create()
        rows = self.rows('SELECT * FROM marcacoes ORDER BY inicio')
        self.create(client=self.client_for(3), barbeiro_id='3', telefone='+351910333444')
        self.assertEqual(self.client_for(3).post(f"/marcacoes/{rows[1]['id']}/cancelar-serie-futura").status_code, 403)
        self.assertEqual(self.client.post(f"/marcacoes/{rows[1]['id']}/cancelar-serie-futura").status_code, 302)
        states = [r['estado'] for r in self.rows('SELECT * FROM marcacoes WHERE barbeiro_id=2 ORDER BY inicio')]
        self.assertEqual(states, ['marcada', 'cancelada', 'cancelada', 'cancelada'])
        self.assertEqual({r['estado'] for r in self.rows('SELECT * FROM marcacoes WHERE barbeiro_id=3')}, {'marcada'})
        self.assertEqual(len(self.rows("SELECT * FROM sms_fila WHERE estado='cancelado'")), 6)
        self.worker()
        own = [text for phone, text in self.sms if phone == '+351910111222'][0]
        self.assertIn(self.start.strftime('%d/%m/%Y'), own)
        self.assertNotIn((self.start+timedelta(weeks=1)).strftime('%d/%m/%Y'), own)

    def test_cancel_all_suppresses_all_sms(self):
        self.create()
        first = self.rows('SELECT id FROM marcacoes ORDER BY inicio')[0]['id']
        self.assertEqual(self.client_for(1).post(f'/marcacoes/{first}/cancelar-serie-futura').status_code, 302)
        self.worker()
        self.assertEqual(self.sms, [])
        self.assertEqual({r['estado'] for r in self.rows('SELECT * FROM sms_fila')}, {'cancelado'})

    def test_sms_permission_checked_again_at_delivery(self):
        self.create()
        with closing(self.mod.get_db()) as con, con:
            con.execute('UPDATE utilizadores SET sms_autorizado=0 WHERE id=2')
        self.worker()
        self.assertEqual(self.sms, [])
        self.assertEqual(self.rows("SELECT estado FROM sms_fila WHERE tipo='confirmacao_serie'")[0]['estado'], 'pendente')

    def test_sms_disabled_creates_no_queue(self):
        with closing(self.mod.get_db()) as con, con:
            con.execute('UPDATE utilizadores SET sms_autorizado=0 WHERE id=2')
        self.assertEqual(self.create().status_code, 302)
        self.assertEqual(self.rows('SELECT * FROM sms_fila'), [])

    def test_concurrent_same_barber_only_one_series(self):
        barrier = threading.Barrier(2)
        def submit(phone):
            client = self.client_for(2)
            barrier.wait()
            return self.create(client=client, telefone=phone).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit, ['+351910111222', '+351910111333']))
        self.assertEqual(sorted(results), [302, 409])
        self.assertEqual(len(self.rows('SELECT * FROM marcacoes')), 4)

    def test_migration_idempotent_and_ui_exposes_series(self):
        self.create()
        before = [tuple(r) for r in self.rows('SELECT * FROM marcacoes')]
        self.mod.garantir_esquema()
        self.mod.garantir_esquema()
        self.assertEqual(before, [tuple(r) for r in self.rows('SELECT * FROM marcacoes')])
        response = self.client.get('/semana', query_string={'data': self.start.date().isoformat()})
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('Repetir semanalmente', text)
        self.assertIn('Cancelar esta e as futuras', text)
        self.assertIn(self.rows('SELECT serie_id FROM marcacoes')[0]['serie_id'], text)

    def test_cross_midnight_conflict_is_rejected(self):
        previous = self.start.replace(hour=23, minute=30) - timedelta(days=1)
        self.create(repetir_semanalmente='0', inicio=previous.isoformat(timespec='minutes'), duracao='90')
        self.assertEqual(self.create(inicio=self.start.replace(hour=0, minute=15).isoformat(timespec='minutes')).status_code, 409)

    def test_pending_online_reservation_blocks_whole_series(self):
        with closing(self.mod.get_db()) as con, con:
            con.execute('''INSERT INTO reservas_online
                (token_publico,barbeiro_id,inicio,duracao_minutos,servico,nome_cliente,telefone_cliente,expira_em)
                VALUES ('test-reservation',2,?,30,'Corte','Reservado','+351910888777',?)''',
                ((self.start+timedelta(weeks=2)).isoformat(timespec='minutes'),
                 (datetime.now().astimezone()+timedelta(minutes=10)).isoformat(timespec='seconds')))
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.rows('SELECT * FROM marcacoes'), [])
        self.assertEqual(self.rows('SELECT * FROM clientes'), [])

    def test_cancel_series_cancels_per_occurrence_emails(self):
        with closing(self.mod.get_db()) as con, con:
            con.execute('UPDATE utilizadores SET email_ativo=1,email_confirmacao=1,email_lembrete_24h=1,email_lembrete_1h=1 WHERE id=2')
            for key in ['email_confirmacao','email_lembrete_24h','email_lembrete_1h']:
                con.execute('''INSERT INTO modelos_comunicacao
                    (chave,canal,nome,assunto,conteudo,conteudo_padrao)
                    VALUES (?,'email',?,'Marcação','{cliente} {data} {hora}','Modelo')''', (key,key))
        self.create(email='test@example.invalid')
        rows = self.rows('SELECT id FROM marcacoes ORDER BY inicio')
        self.assertEqual(len(self.rows('SELECT * FROM email_fila')), 12)
        self.client.post(f"/marcacoes/{rows[1]['id']}/cancelar-serie-futura")
        self.assertEqual(len(self.rows("SELECT * FROM email_fila WHERE estado='cancelado'")), 9)
        self.assertEqual(len(self.rows("SELECT * FROM email_fila WHERE estado='pendente'")), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
