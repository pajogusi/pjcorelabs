#!/usr/bin/env python3
"""Automatic weeks: synthetic database, fixed Lisbon time, no real delivery."""
import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
import tests_series


class WeekTests(unittest.TestCase):
    setUp = tests_series.SeriesTests.setUp
    client_for = tests_series.SeriesTests.client_for

    def context(self, when, query=None, uid=2):
        when = datetime.fromisoformat(when).replace(tzinfo=ZoneInfo('Europe/Lisbon'))
        with patch.object(self.mod, 'agora_barbearia', return_value=when), \
             patch.object(self.mod, 'render_template', return_value='agenda') as render:
            response = self.client_for(uid).get('/semana', query_string=query or {})
        self.assertEqual(response.status_code, 200)
        return render.call_args.kwargs

    def test_friday_threshold_weekend_and_monday(self):
        for when, monday in [('2026-10-09T21:59:59','2026-10-05'),
                             ('2026-10-09T22:00:00','2026-10-12'),
                             ('2026-10-10T10:00:00','2026-10-12'),
                             ('2026-10-11T23:59:59','2026-10-12'),
                             ('2026-10-12T00:00:00','2026-10-12')]:
            with self.subTest(when=when):
                ctx = self.context(when)
                self.assertEqual(ctx['inicio_semana'], date.fromisoformat(monday))
                self.assertTrue(ctx['vista_automatica'])
                self.assertGreater(ctx['viragem_em_ms'], 0)

    def test_explicit_date_stays_put_after_friday(self):
        ctx = self.context('2026-10-09T22:00:00', {'data':'2026-10-07'})
        self.assertEqual(ctx['inicio_semana'], date(2026,10,5))
        self.assertFalse(ctx['vista_automatica'])
        self.assertIsNone(ctx['viragem_em_ms'])

    def test_invalid_date_falls_back_to_automatic_week(self):
        ctx = self.context('2026-10-11T10:00:00', {'data':'2026-99-99'})
        self.assertEqual(ctx['inicio_semana'], date(2026,10,12))
        self.assertTrue(ctx['vista_automatica'])

    def test_year_transition(self):
        ctx = self.context('2027-12-31T22:00:00')
        self.assertEqual(ctx['inicio_semana'], date(2028,1,3))

    def test_refresh_timer_uses_real_elapsed_time_across_dst(self):
        ctx = self.context('2026-10-24T22:00:00')
        # Saturday to next Friday, including the extra hour on Sunday.
        self.assertEqual(ctx['viragem_em_ms'], (6*24+1)*3600*1000)

    def test_week_change_keeps_barber_permissions(self):
        for uid, query, target in [(2, {'barbeiro':'3'},2),
                                   (3, {'barbeiro':'todos'},3),
                                   (1, {'barbeiro':'todos'},None),
                                   (4, {'barbeiro':'3'},3)]:
            with self.subTest(uid=uid):
                ctx = self.context('2026-10-09T22:00:00',query,uid)
                self.assertEqual(ctx['barbeiro_selecionado'],target)
                self.assertEqual(ctx['inicio_semana'],date(2026,10,12))

    def test_rendered_navigation_preserves_auto_and_all_agendas(self):
        with patch.object(self.mod, 'agora_barbearia', return_value=datetime(2026,10,9,21,59,59,tzinfo=ZoneInfo('Europe/Lisbon'))):
            auto = self.client_for(1).get('/semana?barbeiro=todos').get_data(as_text=True)
            manual = self.client_for(1).get('/semana?data=2026-10-05&barbeiro=todos').get_data(as_text=True)
        self.assertIn('const limite = Date.now() + 1000;',auto)
        self.assertNotIn('name="data" value="2026-10-05"',auto)
        self.assertIn('name="data" value="2026-10-05"',manual)
        self.assertNotIn('function verificarSemana()',manual)
        self.assertIn('/semana?data=2026-10-12&barbeiro=todos',auto)
        self.assertIn('/semana?data=2026-09-28&barbeiro=todos',auto)


if __name__ == '__main__':
    unittest.main()
