#!/usr/bin/env python3
"""Synthetic tests for professional absences and global closures."""
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import tests_series


class AbsenceTests(unittest.TestCase):
    setUp = tests_series.SeriesTests.setUp
    client_for = tests_series.SeriesTests.client_for
    rows = tests_series.SeriesTests.rows
    create = tests_series.SeriesTests.create

    def period(self, client=None, **changes):
        data = dict(tipo='ausencia', motivo='Ausência privada B2', barbeiro_id='2',
                    inicio=self.start.isoformat(timespec='minutes'),
                    fim=(self.start+timedelta(hours=2)).isoformat(timespec='minutes'))
        data.update(changes)
        return (client or self.client).post('/indisponibilidades/nova', data=data)

    def availability(self, uid=2, start=None):
        start = start or self.start
        return self.client_for(uid).get('/api/disponibilidade', query_string=dict(
            data=start.date().isoformat(), hora=start.strftime('%H:%M'), duracao=30, barbeiro_id=uid))

    def reserve(self, barber='2', start=None):
        return self.mod.app.test_client().post('/reservar', data=dict(nome='Reserva teste',
            telefone='+351919887766', servico='Corte', barbeiro=barber,
            inicio=(start or self.start).isoformat(timespec='minutes'), duracao=30))

    def test_own_absence_blocks_only_own_agenda(self):
        self.assertEqual(self.period().status_code, 201)
        self.assertFalse(self.availability().json['disponivel'])
        self.assertTrue(self.availability(3).json['disponivel'])
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.create(client=self.client_for(3), barbeiro_id='3').status_code, 302)

    def test_barber_cannot_close_shop_or_create_other_absence(self):
        self.assertEqual(self.period(tipo='encerramento').status_code, 403)
        self.assertEqual(self.period(barbeiro_id='3').status_code, 403)
        self.assertEqual(self.rows('SELECT * FROM indisponibilidades'), [])

    def test_manager_and_admin_can_create_global_closure(self):
        for uid, offset in [(1, 0), (4, 1)]:
            start = self.start+timedelta(days=offset)
            r = self.period(client=self.client_for(uid), tipo='encerramento', inicio=start.isoformat(timespec='minutes'),
                            fim=(start+timedelta(hours=2)).isoformat(timespec='minutes'))
            self.assertEqual(r.status_code, 201)
            self.assertIsNone(r.json['barbeiro_id'])
            for barber in [1, 2, 3]:
                self.assertFalse(self.availability(barber, start).json['disponivel'])

    def test_manager_can_absent_another_professional(self):
        r = self.period(client=self.client_for(1), barbeiro_id='3')
        self.assertEqual(r.status_code, 201)
        row = self.rows('SELECT * FROM indisponibilidades')[0]
        self.assertEqual((row['barbeiro_id'],row['criado_por_id']), (3,1))

    def test_existing_booking_conflict_leaves_everything_unchanged(self):
        self.create(repetir_semanalmente='0')
        before = [tuple(r) for r in self.rows('SELECT * FROM marcacoes')]
        response = self.period()
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json['nada_alterado'])
        self.assertEqual(response.json['conflitos'][0]['nome'], 'Cliente de teste')
        self.assertEqual(before, [tuple(r) for r in self.rows('SELECT * FROM marcacoes')])
        self.assertEqual(self.rows('SELECT * FROM indisponibilidades'), [])

    def test_other_barber_booking_does_not_prevent_absence(self):
        self.create(client=self.client_for(3), barbeiro_id='3')
        self.assertEqual(self.period().status_code, 201)
        self.assertEqual(self.period(client=self.client_for(1), tipo='encerramento').status_code, 409)

    def test_active_reservation_prevents_absence(self):
        self.assertEqual(self.reserve().status_code, 302)
        r = self.period()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json['conflitos'][0]['tipo'], 'reserva')
        self.assertEqual(self.rows('SELECT * FROM indisponibilidades'), [])

    def test_expired_reservation_does_not_prevent_absence(self):
        self.reserve()
        with self.mod.get_db() as con:
            con.execute('UPDATE reservas_online SET expira_em=?', ((datetime.now().astimezone()-timedelta(minutes=1)).isoformat(timespec='seconds'),))
        self.assertEqual(self.period().status_code, 201)

    def test_public_reservation_respects_absence_and_first_available(self):
        self.period()
        self.assertEqual(self.reserve().status_code, 409)
        self.assertEqual(self.reserve(barber='primeiro').status_code, 302)
        self.assertNotEqual(self.rows('SELECT barbeiro_id FROM reservas_online')[0]['barbeiro_id'], 2)

    def test_global_closure_blocks_public_first_available(self):
        self.period(client=self.client_for(1), tipo='encerramento')
        self.assertEqual(self.reserve(barber='primeiro').status_code, 409)
        self.assertEqual(self.rows('SELECT * FROM reservas_online'), [])

    def test_series_later_absence_rejects_whole_series(self):
        later = self.start+timedelta(weeks=2)
        self.period(inicio=later.isoformat(timespec='minutes'), fim=(later+timedelta(hours=1)).isoformat(timespec='minutes'))
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.rows('SELECT * FROM marcacoes'), [])
        self.assertEqual(self.rows('SELECT * FROM clientes'), [])
        self.assertEqual(self.rows('SELECT * FROM sms_fila'), [])

    def test_multiday_period_and_exact_boundaries(self):
        end = (self.start+timedelta(days=3)).replace(hour=0)
        self.period(fim=end.isoformat(timespec='minutes'))
        for dt in [self.start, self.start+timedelta(days=1), end-timedelta(minutes=15)]:
            self.assertFalse(self.availability(start=dt).json['disponivel'])
        self.assertTrue(self.availability(start=end).json['disponivel'])
        self.assertTrue(self.availability(start=self.start-timedelta(minutes=30)).json['disponivel'])

    def test_invalid_periods_and_inactive_professional(self):
        for changes in [dict(tipo='other'), dict(motivo=' '), dict(inicio='bad'),
                        dict(fim=self.start.isoformat(timespec='minutes')),
                        dict(fim=(self.start-timedelta(minutes=1)).isoformat(timespec='minutes')),
                        dict(inicio='2030-01-01T10:00+00:00'), dict(inicio='2030-01-01T10:00:30')]:
            self.assertEqual(self.period(**changes).status_code, 400)
        with self.mod.get_db() as con:
            con.execute('UPDATE utilizadores SET ativo=0 WHERE id=3')
        for barber in ['3', '4', '999']:
            self.assertEqual(self.period(client=self.client_for(1), barbeiro_id=barber).status_code, 400)
        self.assertEqual(self.rows('SELECT * FROM indisponibilidades'), [])

    def test_duplicate_period_rejected_but_other_barber_allowed(self):
        self.assertEqual(self.period().status_code, 201)
        self.assertEqual(self.period().status_code, 409)
        self.assertEqual(self.period(client=self.client_for(3), barbeiro_id='3').status_code, 201)
        self.assertEqual(len(self.rows('SELECT * FROM indisponibilidades')), 2)

    def test_global_and_personal_overlap_rejected(self):
        self.period(client=self.client_for(1), tipo='encerramento')
        self.assertEqual(self.period().status_code, 409)

    def test_delete_permissions_and_release_slot(self):
        pid = self.period().json['id']
        path = f'/indisponibilidades/{pid}/eliminar'
        self.assertEqual(self.client_for(3).post(path).status_code, 403)
        self.assertEqual(self.client.post(path).status_code, 200)
        self.assertTrue(self.availability().json['disponivel'])
        self.assertEqual(self.client.post(path).status_code, 404)
        self.assertEqual(self.create().status_code, 302)

    def test_barber_cannot_delete_global_closure(self):
        pid = self.period(client=self.client_for(1), tipo='encerramento').json['id']
        path = f'/indisponibilidades/{pid}/eliminar'
        self.assertEqual(self.client.post(path).status_code, 403)
        self.assertEqual(self.client_for(4).post(path).status_code, 200)

    def test_duration_cannot_force_overlap_with_absence(self):
        self.create(repetir_semanalmente='0')
        row = self.rows('SELECT id FROM marcacoes')[0]
        start = self.start+timedelta(minutes=30)
        self.assertEqual(self.period(inicio=start.isoformat(timespec='minutes')).status_code, 201)
        for force in ['0', '1']:
            r = self.client.post(f"/marcacoes/{row['id']}/duracao", data=dict(duracao=60, forcar=force))
            self.assertEqual(r.status_code, 409)
        self.assertEqual(self.rows('SELECT duracao_minutos FROM marcacoes')[0]['duracao_minutos'], 30)

    def test_cancelled_booking_cannot_restore_into_closure(self):
        self.create(repetir_semanalmente='0')
        mid = self.rows('SELECT id FROM marcacoes')[0]['id']
        self.client.post(f'/marcacoes/{mid}/estado', data=dict(estado='cancelada'))
        self.period()
        self.assertEqual(self.client.post(f'/marcacoes/{mid}/estado', data=dict(estado='marcada')).status_code, 409)
        self.assertEqual(self.rows('SELECT estado FROM marcacoes')[0]['estado'], 'cancelada')

    def test_weekly_visibility_and_private_reasons(self):
        self.period()
        self.period(client=self.client_for(3), barbeiro_id='3', motivo='Motivo privado B3')
        date = self.start.date().isoformat()
        own = self.client.get('/semana', query_string={'data':date}).get_data(as_text=True)
        self.assertIn('Ausência privada B2', own)
        self.assertNotIn('Motivo privado B3', own)
        self.assertIn('tipoIndisponibilidade', own)
        self.assertNotIn('<option value="encerramento">', own)
        all_agendas = self.client_for(1).get('/semana', query_string={'data':date,'barbeiro':'todos'}).get_data(as_text=True)
        self.assertIn('Ausência privada B2', all_agendas)
        self.assertIn('Motivo privado B3', all_agendas)
        self.assertIn('<option value="encerramento">', all_agendas)

    def test_migration_preserves_existing_data(self):
        self.create()
        self.period(inicio=(self.start+timedelta(days=1)).isoformat(timespec='minutes'), fim=(self.start+timedelta(days=2)).isoformat(timespec='minutes'))
        before = {table:[tuple(r) for r in self.rows(f'SELECT * FROM {table}')] for table in ['marcacoes','clientes','indisponibilidades']}
        self.mod.garantir_esquema()
        self.mod.garantir_esquema()
        for table, values in before.items():
            self.assertEqual(values,[tuple(r) for r in self.rows(f'SELECT * FROM {table}')])

    def test_booking_and_absence_race_cannot_both_succeed(self):
        barrier = threading.Barrier(2)
        def booking():
            client = self.client_for(2); barrier.wait()
            return self.create(client=client).status_code
        def absence():
            client = self.client_for(2); barrier.wait()
            return self.period(client=client).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(booking), pool.submit(absence)
            results = [a.result(), b.result()]
        self.assertIn(409, results)
        self.assertFalse(self.rows('SELECT * FROM marcacoes') and self.rows('SELECT * FROM indisponibilidades'))

    def test_online_reservation_and_absence_race_cannot_both_succeed(self):
        barrier = threading.Barrier(2)
        def reserve():
            barrier.wait(); return self.reserve().status_code
        def absence():
            client = self.client_for(2); barrier.wait()
            return self.period(client=client).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(reserve), pool.submit(absence)
            results = [a.result(), b.result()]
        self.assertIn(409, results)
        self.assertFalse(self.rows('SELECT * FROM reservas_online') and self.rows('SELECT * FROM indisponibilidades'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
