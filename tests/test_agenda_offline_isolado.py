"""Testes isolados do endpoint de agenda offline. Não utiliza a BD de produção."""
import ast
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
tree.body = [node for node in tree.body if not (
    isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    and isinstance(node.value.func, ast.Name) and node.value.func.id == "garantir_esquema"
)]
namespace = {"__name__": "blessed_teste", "__file__": str(ROOT / "app.py")}
exec(compile(tree, str(ROOT / "app.py"), "exec"), namespace)
app = namespace["app"]
endpoint = namespace["agenda_snapshot_offline"]


class TestAgendaOffline(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE marcacoes (barbeiro_id INTEGER, inicio TEXT, duracao_minutos INTEGER, estado TEXT);
        CREATE TABLE reservas_online (barbeiro_id INTEGER, inicio TEXT, duracao_minutos INTEGER, estado TEXT, expira_em TEXT);
        CREATE TABLE bloqueios_pessoais (barbeiro_id INTEGER, inicio TEXT, duracao_minutos INTEGER);
        CREATE TABLE indisponibilidades (barbeiro_id INTEGER, inicio TEXT, fim TEXT, tipo TEXT);
        """)
        self.today = namespace["agora_barbearia"]().date()
        self.date = (self.today + timedelta(days=2)).isoformat()
        self.start = self.date + "T10:00"
        self.end = self.date + "T10:30"

    def tearDown(self):
        try: self.db.close()
        except sqlite3.ProgrammingError: pass

    def call(self, user=None):
        if user is None:
            user = {"id": 1, "papel": "gestor", "ativo": 1}
        with app.test_request_context("/api/agenda/offline"):
            with patch.dict(endpoint.__globals__, {
                "utilizador_atual": lambda: user,
                "get_db": lambda: self.db,
            }):
                response = endpoint()
                if isinstance(response, tuple):
                    return response[0], response[1], None
                return response.get_json(), response.status_code, response

    def test_sem_autenticacao(self):
        with app.test_request_context("/api/agenda/offline"):
            with patch.dict(endpoint.__globals__, {"utilizador_atual": lambda: None}):
                response = endpoint()
        self.assertEqual(response[1], 401)

    def test_agenda_vazia(self):
        data, status, response = self.call()
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["intervalos"], [])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_marcacao_ativa_e_cancelada(self):
        self.db.executemany("INSERT INTO marcacoes VALUES (?,?,?,?)", [
            (1, self.start, 30, "confirmada"),
            (1, self.date + "T12:00", 30, "cancelada"),
        ])
        data, status, _ = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(data["intervalos"], [
            {"barbeiro_id": 1, "inicio": self.start, "fim": self.end}
        ])

    def test_reserva_ativa_e_expirada(self):
        futuro = (datetime.now().astimezone() + timedelta(days=3)).isoformat(timespec="seconds")
        passado = (datetime.now().astimezone() - timedelta(days=3)).isoformat(timespec="seconds")
        self.db.executemany("INSERT INTO reservas_online VALUES (?,?,?,?,?)", [
            (1, self.start, 30, "aguarda_pagamento", futuro),
            (1, self.date + "T12:00", 30, "aguarda_pagamento", passado),
        ])
        data, _, _ = self.call()
        self.assertEqual(len(data["intervalos"]), 1)

    def test_bloqueio_pessoal(self):
        self.db.execute("INSERT INTO bloqueios_pessoais VALUES (?,?,?)", (2, self.start, 60))
        data, _, _ = self.call()
        self.assertEqual(data["intervalos"][0]["fim"], self.date + "T11:00")
        self.assertEqual(data["intervalos"][0]["barbeiro_id"], 2)

    def test_encerramento_global_e_ausencia_individual(self):
        self.db.executemany("INSERT INTO indisponibilidades VALUES (?,?,?,?)", [
            (1, self.start, self.end, "encerramento"),
            (2, self.date + "T12:00", self.date + "T13:00", "ausencia"),
        ])
        data, _, _ = self.call()
        self.assertEqual(len(data["intervalos"]), 2)
        self.assertIsNone(data["intervalos"][0]["barbeiro_id"])
        self.assertEqual(data["intervalos"][1]["barbeiro_id"], 2)

    def test_periodo_de_45_dias(self):
        data, _, _ = self.call()
        self.assertEqual(data["desde"], self.today.isoformat())
        self.assertEqual(data["ate"], (self.today + timedelta(days=45)).isoformat())


if __name__ == "__main__":
    unittest.main(verbosity=2)
