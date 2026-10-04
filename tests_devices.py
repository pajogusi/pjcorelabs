#!/usr/bin/env python3
"""Browser identity and activity logs: synthetic SQLite, mocked email only."""
import csv
import io
import unittest
from contextlib import closing
from unittest.mock import patch
from werkzeug.security import generate_password_hash
import tests_series


class DeviceTests(unittest.TestCase):
    setUp = tests_series.SeriesTests.setUp
    client_for = tests_series.SeriesTests.client_for
    rows = tests_series.SeriesTests.rows

    def browser(self, uid=2):
        client=self.client_for(uid)
        response=client.get('/equipamento')
        self.assertEqual(response.status_code,200)
        cookie=client.get_cookie(self.mod.EQUIPAMENTO_COOKIE)
        device=self.rows('SELECT * FROM equipamentos WHERE id=?',(cookie.value,))[0]
        return client,dict(device)

    def name(self, client, device, name='Tablet da loja', **changes):
        data={'nome':name,'csrf_token':device['csrf_token']};data.update(changes)
        return client.post('/equipamento/nome',data=data)

    def test_cookie_is_unique_persistent_and_separate_from_production(self):
        first,device=self.browser()
        cookie=first.get_cookie(self.mod.EQUIPAMENTO_COOKIE)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site,'Lax')
        self.assertNotEqual(cookie.key,'blessed_equipamento')
        second,other=self.browser(3)
        self.assertNotEqual(device['id'],other['id'])
        first.get('/semana')
        self.assertEqual(first.get_cookie(self.mod.EQUIPAMENTO_COOKIE).value,device['id'])
        self.assertEqual(len(self.rows('SELECT * FROM equipamentos')),2)
        https_client=self.client_for(2)
        https_client.get('/equipamento',base_url='https://localhost')
        self.assertTrue(https_client.get_cookie(self.mod.EQUIPAMENTO_COOKIE).secure)

    def test_unknown_or_invalid_cookie_is_replaced_not_adopted(self):
        for value in ['invalid', 'a'*32]:
            client=self.client_for(2)
            client.set_cookie(self.mod.EQUIPAMENTO_COOKIE,value)
            client.get('/equipamento')
            self.assertNotEqual(client.get_cookie(self.mod.EQUIPAMENTO_COOKIE).value,value)

    def test_name_changes_only_this_browser_and_requires_its_token(self):
        first,device=self.browser()
        second,other=self.browser(3)
        self.assertEqual(self.name(first,device,csrf_token=other['csrf_token']).status_code,403)
        self.assertEqual(self.name(first,device,'  Tablet   da loja  ').status_code,302)
        self.assertEqual(self.rows('SELECT nome FROM equipamentos WHERE id=?',(device['id'],))[0]['nome'],'Tablet da loja')
        self.assertEqual(self.rows('SELECT nome FROM equipamentos WHERE id=?',(other['id'],))[0]['nome'],'')
        self.assertIn('Tablet da loja',first.get('/equipamento').get_data(as_text=True))
        self.assertEqual(self.mod.app.test_client().post('/equipamento/nome',data={'nome':'Sem login'}).status_code,302)

    def test_name_validation_and_html_escaping(self):
        client,device=self.browser()
        for name in ['', ' '*3, 'x'*81, 'Tablet\x00', 'Tablet\nLoja']:
            self.assertEqual(self.name(client,device,name).status_code,400)
        self.assertEqual(self.name(client,device,'<img src=x onerror=alert(1)>').status_code,302)
        html=client.get('/equipamento').get_data(as_text=True)
        self.assertIn('&lt;img',html)
        self.assertNotIn('value="<img',html)

    def test_logged_action_has_user_device_type_and_status(self):
        client,device=self.browser()
        self.name(client,device)
        self.mod.app.config['TESTING']=False
        client.get('/semana',headers={'User-Agent':'Mozilla iPhone','CF-Connecting-IP':'192.0.2.10'})
        row=self.rows('SELECT * FROM atividade_log ORDER BY id DESC LIMIT 1')[0]
        self.assertEqual((row['utilizador_id'],row['utilizador_nome'],row['utilizador_username']),(2,'B2','b2'))
        self.assertEqual((row['equipamento_id'],row['equipamento_nome']),(device['id'],'Tablet da loja'))
        self.assertEqual((row['dispositivo'],row['user_agent']),('Telemóvel (iPhone)','Mozilla iPhone'))
        self.assertEqual((row['estado_http'],row['ip']),(200,'192.0.2.10'))
        self.assertEqual(row['equipamento_novo'],0)

    def test_device_and_actor_snapshots_survive_rename_and_logout(self):
        client,device=self.browser();self.name(client,device,'Centro')
        self.mod.app.config['TESTING']=False
        client.get('/semana')
        first=self.rows('SELECT * FROM atividade_log ORDER BY id DESC LIMIT 1')[0]
        self.name(client,device,'Sombra')
        client.get('/logout')
        logout=self.rows('SELECT * FROM atividade_log ORDER BY id DESC LIMIT 1')[0]
        unchanged=self.rows('SELECT * FROM atividade_log WHERE id=?',(first['id'],))[0]
        self.assertEqual(unchanged['equipamento_nome'],'Centro')
        self.assertEqual((logout['utilizador_id'],logout['equipamento_nome'],logout['caminho']),(2,'Sombra','/logout'))

    def test_login_logs_authenticated_actor_and_failure_has_no_actor(self):
        with closing(self.mod.get_db()) as con, con:
            con.execute('UPDATE utilizadores SET password_hash=? WHERE id=2',(generate_password_hash('test-only'),))
        self.mod.app.config['TESTING']=False
        client=self.mod.app.test_client()
        client.post('/login',data={'username':'b2','password':'wrong'})
        failed=self.rows('SELECT * FROM atividade_log ORDER BY id DESC LIMIT 1')[0]
        self.assertIsNone(failed['utilizador_id']);self.assertEqual(failed['estado_http'],401)
        client.post('/login',data={'username':'b2','password':'test-only'})
        success=self.rows('SELECT * FROM atividade_log ORDER BY id DESC LIMIT 1')[0]
        self.assertEqual(success['utilizador_id'],2)
        self.assertEqual(success['equipamento_id'],failed['equipamento_id'])

    def test_new_browser_marker_and_static_requests_are_not_logged(self):
        self.mod.app.config['TESTING']=False
        client=self.client_for(2)
        client.get('/equipamento')
        self.assertEqual(self.rows('SELECT equipamento_novo FROM atividade_log')[0]['equipamento_novo'],1)
        client.get('/static/equipamento.css').close()
        self.assertEqual(len(self.rows('SELECT * FROM atividade_log')),1)
        client.get('/equipamento')
        self.assertEqual(self.rows('SELECT equipamento_novo FROM atividade_log ORDER BY id DESC LIMIT 1')[0]['equipamento_novo'],0)

    def test_logs_stay_admin_only_and_include_device_on_screen(self):
        client,device=self.browser();self.name(client,device,'Sombra')
        self.mod.app.config['TESTING']=False
        client.get('/semana')
        for uid in [1,2,3]:
            self.assertNotEqual(self.client_for(uid).get('/admin').status_code,200)
        response=self.client_for(4).get('/admin')
        self.assertEqual(response.status_code,200)
        self.assertIn('Sombra',response.get_data(as_text=True))
        self.assertIn('b2',response.get_data(as_text=True))
        self.assertIn('/admin#admin-logs',self.client_for(4).get('/semana').get_data(as_text=True))
        self.assertNotIn('/admin#admin-logs',client.get('/semana').get_data(as_text=True))

    def test_csv_export_has_devices_safe_cells_and_remains_manual(self):
        client,device=self.browser();self.name(client,device,'=SUM(1,1)')
        self.mod.app.config['TESTING']=False
        with patch.object(self.mod,'enviar_email_brevo',return_value=True) as send:
            client.get('/semana')
            send.assert_not_called()
            response=self.client_for(4).post('/admin/logs/enviar',data={'modo':'lote','lote':'50'})
        self.assertEqual(response.status_code,302)
        csv_text=send.call_args.kwargs['anexo_conteudo'].decode('utf-8-sig')
        exported=list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(exported[0]['Equipamento'],"'=SUM(1,1)")
        self.assertEqual(exported[0]['Utilizador'],'B2')
        self.assertEqual(exported[0]['Equipamento ID'],device['id'])

    def test_additive_migration_preserves_old_logs_and_is_repeatable(self):
        with closing(self.mod.get_db()) as con, con:
            con.execute('DROP TABLE atividade_log')
            con.execute('CREATE TABLE atividade_log (id INTEGER PRIMARY KEY, criado_em TEXT, metodo TEXT, caminho TEXT, estado_http INTEGER, ip TEXT, enviado_em TEXT)')
            con.execute("INSERT INTO atividade_log VALUES (1,'2026-01-01','GET','/semana',200,'old-ip',NULL)")
        self.mod.garantir_esquema();self.mod.garantir_esquema()
        old=self.rows('SELECT * FROM atividade_log WHERE id=1')[0]
        self.assertEqual(old['ip'],'old-ip');self.assertIsNone(old['equipamento_id'])
        self.assertEqual(old['equipamento_novo'],0)


if __name__ == '__main__':
    unittest.main()
