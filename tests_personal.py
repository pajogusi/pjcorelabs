#!/usr/bin/env python3
"""Personal commitments and production-style appointment tabs, on synthetic data."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from html.parser import HTMLParser
import tests_series
import tests_absences


class PlacementParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.ancestors = {}
        self.void = {'input','img','link','meta','br','hr','source'}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ancestors[attrs['id']] = [a for _, a in self.stack]
        if tag not in self.void:
            self.stack.append((tag, attrs.get('id')))

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break


class PersonalTests(unittest.TestCase):
    setUp = tests_series.SeriesTests.setUp
    client_for = tests_series.SeriesTests.client_for
    rows = tests_series.SeriesTests.rows
    create = tests_series.SeriesTests.create
    period = tests_absences.AbsenceTests.period
    availability = tests_absences.AbsenceTests.availability
    reserve = tests_absences.AbsenceTests.reserve

    def personal(self, client=None, **changes):
        data = dict(descricao='Massagem pessoal B2', inicio=self.start.isoformat(timespec='minutes'), duracao='60', barbeiro_id='2')
        data.update(changes)
        return (client or self.client).post('/bloqueios/novo', data=data)

    def test_personal_creates_no_client_or_communication(self):
        self.assertEqual(self.personal().status_code, 201)
        row = self.rows('SELECT * FROM bloqueios_pessoais')[0]
        self.assertEqual((row['barbeiro_id'],row['criado_por_id']), (2,2))
        for table in ['clientes','marcacoes','sms_fila','email_fila']:
            self.assertEqual(self.rows(f'SELECT * FROM {table}'), [])
        self.assertFalse(self.availability().json['disponivel'])
        self.assertTrue(self.availability(3).json['disponivel'])

    def test_personal_preview_accepts_full_duration_range(self):
        query = dict(data=self.start.date().isoformat(),hora=self.start.strftime('%H:%M'),duracao=120,barbeiro_id=2,tipo='pessoal')
        response = self.client.get('/api/disponibilidade',query_string=query)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['disponivel'])
        query['tipo']='cliente'
        self.assertEqual(self.client.get('/api/disponibilidade',query_string=query).status_code,400)

    def test_personal_times_isolated_and_foreign_target_rejected(self):
        self.personal()
        self.assertEqual(self.personal(client=self.client_for(3),barbeiro_id='3').status_code, 201)
        self.assertEqual(self.personal(barbeiro_id='3').status_code, 403)
        self.assertEqual(len(self.rows('SELECT * FROM bloqueios_pessoais')), 2)

    def test_manager_and_admin_can_create_for_other_barber(self):
        for uid, offset in [(1,0),(4,1)]:
            response=self.personal(client=self.client_for(uid),barbeiro_id='3',inicio=(self.start+timedelta(days=offset)).isoformat(timespec='minutes'))
            self.assertEqual(response.status_code,201)
            self.assertEqual(response.json['barbeiro_id'],3)
        self.assertEqual({r['criado_por_id'] for r in self.rows('SELECT * FROM bloqueios_pessoais')},{1,4})

    def test_edit_delete_permissions_and_ignore_self(self):
        pid=self.personal().json['id']
        data=dict(descricao='Alterado',inicio=self.start.isoformat(timespec='minutes'),duracao='90',barbeiro_id='3')
        path=f'/bloqueios/{pid}'
        self.assertEqual(self.client_for(3).post(path+'/editar',data=data).status_code,403)
        self.assertEqual(self.client_for(3).post(path+'/eliminar').status_code,403)
        self.assertEqual(self.client.post(path+'/editar',data=data).status_code,200)
        row=self.rows('SELECT * FROM bloqueios_pessoais')[0]
        self.assertEqual(row['barbeiro_id'],2)  # editing cannot transfer a commitment
        self.assertEqual(row['duracao_minutos'],90)
        self.assertEqual(self.client_for(1).post(path+'/eliminar').status_code,200)
        self.assertEqual(self.client.post(path+'/eliminar').status_code,404)
        self.assertTrue(self.availability().json['disponivel'])

    def test_personal_blocks_single_series_and_online_bookings(self):
        self.personal(inicio=(self.start+timedelta(weeks=2)).isoformat(timespec='minutes'))
        self.assertEqual(self.create().status_code,409)
        self.assertEqual(self.rows('SELECT * FROM marcacoes'),[])
        later=self.start+timedelta(weeks=2)
        self.assertEqual(self.reserve(start=later).status_code,409)
        self.assertEqual(self.create(repetir_semanalmente='0',inicio=later.isoformat(timespec='minutes')).status_code,409)
        self.assertEqual(self.create(client=self.client_for(3),barbeiro_id='3',inicio=later.isoformat(timespec='minutes')).status_code,302)

    def test_personal_cannot_overlap_bookings_or_reservations(self):
        self.create(repetir_semanalmente='0')
        self.assertEqual(self.personal().status_code,409)
        self.reserve(start=self.start+timedelta(days=1))
        self.assertEqual(self.personal(inicio=(self.start+timedelta(days=1)).isoformat(timespec='minutes')).status_code,409)
        self.assertEqual(self.rows('SELECT * FROM bloqueios_pessoais'),[])

    def test_personal_and_absence_closure_conflicts(self):
        self.personal()
        self.assertEqual(self.period().status_code,409)
        self.assertEqual(self.period(client=self.client_for(1),tipo='encerramento').status_code,409)
        self.assertEqual(self.period(client=self.client_for(3),barbeiro_id='3').status_code,201)
        self.assertEqual(self.personal(client=self.client_for(3),barbeiro_id='3').status_code,409)

    def test_global_closure_blocks_personal(self):
        self.period(client=self.client_for(1),tipo='encerramento')
        self.assertEqual(self.personal().status_code,409)
        self.assertEqual(self.personal(client=self.client_for(3),barbeiro_id='3').status_code,409)

    def test_personal_blocks_forced_duration_and_restore(self):
        self.create(repetir_semanalmente='0')
        mid=self.rows('SELECT id FROM marcacoes')[0]['id']
        self.personal(inicio=(self.start+timedelta(minutes=30)).isoformat(timespec='minutes'))
        self.assertEqual(self.client.post(f'/marcacoes/{mid}/duracao',data=dict(duracao=60,forcar='1')).status_code,409)
        self.client.post(f'/marcacoes/{mid}/estado',data=dict(estado='cancelada'))
        self.assertEqual(self.personal(duracao='30').status_code,201)
        self.assertEqual(self.client.post(f'/marcacoes/{mid}/estado',data=dict(estado='marcada')).status_code,409)

    def test_invalid_personal_data_and_missing_id(self):
        for changes in [dict(descricao=' '),dict(inicio='bad'),dict(inicio='2030-01-01T10:00+00:00'),dict(duracao='14'),dict(duracao='241'),dict(duracao='abc')]:
            self.assertEqual(self.personal(**changes).status_code,400)
        self.assertEqual(self.personal(client=self.client_for(1),barbeiro_id='999').status_code,400)
        self.assertEqual(self.rows('SELECT * FROM bloqueios_pessoais'),[])
        data=dict(descricao='Test',inicio=self.start.isoformat(timespec='minutes'),duracao=60)
        self.assertEqual(self.client.post('/bloqueios/999/editar',data=data).status_code,404)

    def test_edit_conflict_preserves_original(self):
        pid=self.personal().json['id']
        self.create(repetir_semanalmente='0',inicio=(self.start+timedelta(days=1)).isoformat(timespec='minutes'))
        before=[tuple(r) for r in self.rows('SELECT * FROM bloqueios_pessoais')]
        response=self.client.post(f'/bloqueios/{pid}/editar',data=dict(descricao='Moved',inicio=(self.start+timedelta(days=1)).isoformat(timespec='minutes'),duracao=60))
        self.assertEqual(response.status_code,409)
        self.assertEqual(before,[tuple(r) for r in self.rows('SELECT * FROM bloqueios_pessoais')])

    def test_three_tabs_inside_same_appointment_modal(self):
        response=self.client.get('/semana',query_string=dict(data=self.start.date().isoformat()))
        self.assertEqual(response.status_code,200)
        text=response.get_data(as_text=True)
        parser=PlacementParser();parser.feed(text)
        for ident in ['modoCliente','modoPessoal','modoIndisponibilidade','formNovaMarcacao','formPessoal','formIndisponibilidade']:
            self.assertIn('modalMarcacao',parser.ancestors[ident])
        self.assertNotIn('painelPeriodos',parser.ancestors)
        self.assertIn('Dia inteiro',text)
        self.assertIn('Data inicial',text)
        self.assertIn('Data final',text)

    def test_grid_blocks_and_privacy(self):
        self.personal()
        self.personal(client=self.client_for(3),barbeiro_id='3',descricao='Privado B3')
        date=self.start.date().isoformat()
        own=self.client.get('/semana',query_string=dict(data=date)).get_data(as_text=True)
        self.assertIn('bloqueio-pessoal',own)
        self.assertIn('Massagem pessoal B2',own)
        self.assertNotIn('Privado B3',own)
        all_agendas=self.client_for(1).get('/semana',query_string=dict(data=date,barbeiro='todos')).get_data(as_text=True)
        self.assertIn('Privado B3',all_agendas)
        self.assertIn('data-pode-alterar="1"',all_agendas)

    def test_multiday_absence_is_visible_as_blocks(self):
        self.period(inicio=self.start.replace(hour=0).isoformat(timespec='minutes'),fim=(self.start+timedelta(days=2)).replace(hour=0).isoformat(timespec='minutes'))
        text=self.client.get('/semana',query_string=dict(data=self.start.date().isoformat())).get_data(as_text=True)
        self.assertEqual(text.count('data-tipo="ausencia"'),2)
        self.assertIn('--duracao: 900;',text)

    def test_personal_and_booking_race_cannot_both_succeed(self):
        barrier=threading.Barrier(2)
        def book():
            client=self.client_for(2);barrier.wait();return self.create(client=client).status_code
        def block():
            client=self.client_for(2);barrier.wait();return self.personal(client=client).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b=pool.submit(book),pool.submit(block)
            results=[a.result(),b.result()]
        self.assertIn(409,results)
        self.assertFalse(self.rows('SELECT * FROM marcacoes') and self.rows('SELECT * FROM bloqueios_pessoais'))


if __name__=='__main__':
    unittest.main(verbosity=2)
