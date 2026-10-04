#!/usr/bin/env python3
"""Client lookup and selected identity, on an isolated synthetic database."""
import unittest
from contextlib import closing
from datetime import timedelta
import tests_series


class ClientSearchTests(unittest.TestCase):
    setUp = tests_series.SeriesTests.setUp
    client_for = tests_series.SeriesTests.client_for
    rows = tests_series.SeriesTests.rows
    create = tests_series.SeriesTests.create

    def add_client(self, name='José Silva', owner=2, phone='+351910111222'):
        with closing(self.mod.get_db()) as con, con:
            cid = con.execute('INSERT INTO clientes (nome,email,data_nascimento,barbeiro_id) VALUES (?,?,?,?)',
                              (name,'cliente@example.test','1980-03-12',owner)).lastrowid
            if phone:
                con.execute('INSERT INTO telefones (cliente_id,numero,numero_normalizado,atual) VALUES (?,?,?,1)',
                            (cid,phone,self.mod.normalizar_telefone(phone)))
        return cid

    def search(self, name, client=None):
        return (client or self.client).get('/api/clientes/por-nome',query_string={'nome':name})

    def test_lookup_routes_require_login(self):
        for url in ['/api/clientes/por-nome?nome=Jose','/api/clientes/por-telefone?telefone=910111222','/api/clientes/1/marcacao']:
            with self.subTest(url=url):
                self.assertEqual(self.mod.app.test_client().get(url).status_code,302)

    def test_partial_accent_and_case_insensitive_names(self):
        cid = self.add_client()
        for name in ['JOSE','josé','Silv','osé Si']:
            with self.subTest(name=name):
                result=self.search(name).json
                self.assertEqual([c['id'] for c in result['clientes']],[cid])
                self.assertEqual(result['clientes'][0]['telefone'],'+351910111222')

    def test_same_names_remain_distinct_and_foreign_names_hidden(self):
        ids=[self.add_client(phone='+351910111222'),self.add_client(phone='+351910111223')]
        foreign=self.add_client(owner=3,phone='+351910111224')
        self.assertEqual({c['id'] for c in self.search('Jose').json['clientes']},set(ids))
        for uid in [1,4]:
            self.assertEqual({c['id'] for c in self.search('Jose',self.client_for(uid)).json['clientes']},set(ids+[foreign]))
        self.assertEqual([c['id'] for c in self.search('Jose',self.client_for(3)).json['clientes']],[foreign])

    def test_short_long_and_literal_search_text(self):
        self.add_client()
        literal=self.add_client(name="D'Ávila 100%_",phone='+351910111223')
        self.assertEqual(self.search('J').json['clientes'],[])
        self.assertEqual(self.search('x'*81).status_code,400)
        self.assertEqual(self.search("' OR 1=1 --").json['clientes'],[])
        for name in ["D'avila",'%_']:
            self.assertEqual([c['id'] for c in self.search(name).json['clientes']],[literal])

    def test_result_limit_and_refinement_hint(self):
        for i in range(22): self.add_client(name=f'Cliente {i:02}',phone=f'+35191011{i:04}')
        response=self.search('Cliente').json
        self.assertEqual(len(response['clientes']),20)
        self.assertTrue(response['mais_resultados'])
        self.assertFalse(self.search('Cliente 21').json['mais_resultados'])

    def test_phone_lookup_does_not_disclose_foreign_client(self):
        cid=self.add_client(owner=3)
        response=self.client.get('/api/clientes/por-telefone?telefone=+351910111222')
        self.assertFalse(response.json['encontrado'])
        response=self.client_for(3).get('/api/clientes/por-telefone',query_string={'telefone':'+351910111222'})
        self.assertEqual(response.json['cliente']['id'],cid)

    def test_detail_permissions_and_history_are_scoped(self):
        cid=self.add_client()
        with closing(self.mod.get_db()) as con, con:
            for owner in [2,3]:
                con.execute('INSERT INTO marcacoes (cliente_id,inicio,duracao_minutos,barbeiro_id) VALUES (?,?,30,?)',
                            (cid,(self.start+timedelta(days=owner)).isoformat(timespec='minutes'),owner))
        url=f'/api/clientes/{cid}/marcacao'
        own=self.client.get(url).json['cliente']
        self.assertEqual(own['email'],'cliente@example.test')
        self.assertEqual(own['data_nascimento'],'1980-03-12')
        self.assertEqual(len(own['ultimas_visitas']),1)
        self.assertEqual(len(self.client_for(1).get(url).json['cliente']['ultimas_visitas']),2)
        self.assertEqual(self.client_for(3).get(url).status_code,404)
        self.assertEqual(self.client.get('/api/clientes/99999/marcacao').status_code,404)
        phone=self.client.get('/api/clientes/por-telefone',query_string={'telefone':'+351910111222'}).json
        self.assertEqual(len(phone['cliente']['ultimas_visitas']),1)

    def test_selected_identity_avoids_duplicate_shared_phone_mixup(self):
        own=self.add_client()
        foreign=self.add_client(owner=3)
        response=self.create(nome='José Silva',cliente_id=str(own),repetir_semanalmente='0')
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.rows('SELECT cliente_id FROM marcacoes')[0]['cliente_id'],own)
        self.assertEqual(len(self.rows('SELECT * FROM clientes')),2)
        self.assertEqual(self.rows('SELECT barbeiro_id FROM clientes WHERE id=?',(foreign,))[0]['barbeiro_id'],3)

    def test_forged_selection_and_changed_phone_do_not_create_clients(self):
        own=self.add_client()
        foreign=self.add_client(owner=3,phone='+351910111223')
        for selected,phone,status in [(foreign,'+351910111222',403),(99999,'+351910111222',403),
                                      (own,'+351910111999',409),('oops','+351910111222',400),
                                      ('²','+351910111222',400),('9'*30,'+351910111222',400)]:
            with self.subTest(selected=selected):
                response=self.create(cliente_id=str(selected),telefone=phone,repetir_semanalmente='0')
                self.assertEqual(response.status_code,status)
        self.assertEqual(self.rows('SELECT * FROM marcacoes'),[])
        self.assertEqual(len(self.rows('SELECT * FROM clientes')),2)

    def test_manager_selected_client_can_book_with_other_barber_and_series(self):
        cid=self.add_client(owner=3)
        response=self.create(client=self.client_for(1),cliente_id=str(cid),barbeiro_id='2')
        self.assertEqual(response.status_code,302)
        self.assertEqual({r['cliente_id'] for r in self.rows('SELECT * FROM marcacoes')},{cid})
        self.assertEqual(len(self.rows('SELECT * FROM clientes')),1)

    def test_selected_client_without_phone_keeps_existing_record(self):
        cid=self.add_client(phone=None)
        self.assertIsNone(self.search('Jose').json['clientes'][0]['telefone'])
        response=self.create(cliente_id=str(cid),repetir_semanalmente='0')
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.rows('SELECT cliente_id FROM marcacoes')[0]['cliente_id'],cid)
        self.assertEqual(len(self.rows('SELECT * FROM clientes')),1)
        self.assertEqual(self.rows('SELECT cliente_id FROM telefones')[0]['cliente_id'],cid)


if __name__ == '__main__':
    unittest.main()
