import os
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import inspect, text
from sqlalchemy.dialects import mysql

from tests import test_loan_mysql as fixtures
from scripts.upgrade_space_reservation_schema import upgrade


class SpaceSchemaUpgradePlanTest(unittest.TestCase):
    def columns(self):
        return [{"name":"note", "type":mysql.TEXT(), "nullable":False, "default":None, "comment":None},
            {"name":"review_note", "type":mysql.VARCHAR(255), "nullable":False, "default":None, "comment":None}]

    def test_preview_is_read_only_and_preserves_text_type(self):
        engine=Mock(dialect=mysql.dialect())
        inspector=Mock()
        inspector.get_columns.return_value=self.columns()
        with patch("scripts.upgrade_space_reservation_schema.inspect",return_value=inspector):
            statements=upgrade(engine)
        self.assertEqual(len(statements),1)
        self.assertIn("note TEXT NULL",statements[0])
        self.assertIn("review_note VARCHAR(500) NULL",statements[0])
        engine.begin.assert_not_called()

    def test_repeat_never_narrows_larger_columns_and_preserves_defaults(self):
        engine=Mock(dialect=mysql.dialect())
        inspector=Mock()
        columns=self.columns()
        columns[0].update(nullable=True)
        columns[1].update(type=mysql.VARCHAR(1000),nullable=True)
        inspector.get_columns.return_value=columns
        with patch("scripts.upgrade_space_reservation_schema.inspect",return_value=inspector):
            self.assertEqual(upgrade(engine),[])
            columns[1].update(nullable=False,default="'原默认值'",comment="审核'说明")
            statement=upgrade(engine)[0]
            self.assertIn("VARCHAR(1000)",statement)
            self.assertIn("DEFAULT '原默认值'",statement)
            self.assertIn("COMMENT",statement)


@unittest.skipUnless(os.environ.get("MYSQL_LIBRARY_TEST_URL") or os.environ.get("RUN_LIBRARY_MYSQL_TEST")=="1",
    "需显式启用独立 MySQL 临时库升级测试")
class SpaceSchemaUpgradeMySQLTest(unittest.TestCase):
    setUpClass=classmethod(fixtures.LoanMySQLConcurrencyTest.setUpClass.__func__)
    dispose_test_database=classmethod(fixtures.LoanMySQLConcurrencyTest.dispose_test_database.__func__)

    def test_old_rows_survive_preview_upgrade_and_repeat_without_truncation(self):
        # Use a separate old-shape table in this disposable database, never the real library.
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE agent_reservation_actions"))
            connection.execute(text("DROP TABLE reservations"))
            connection.execute(text("CREATE TABLE reservations (id INTEGER PRIMARY KEY, note TEXT NOT NULL, review_note VARCHAR(255) NOT NULL)"))
            connection.execute(text("INSERT INTO reservations VALUES (1,:note,:review)"),
                {"note":"既有长备注"*400,"review":"已有审核内容"})
            before=connection.execute(text("SELECT * FROM reservations ORDER BY id")).all()
        self.assertEqual(len(upgrade(self.engine)),1)
        self.assertFalse(next(c for c in inspect(self.engine).get_columns("reservations") if c["name"]=="note")["nullable"])
        self.assertEqual(len(upgrade(self.engine,apply=True)),1)
        self.assertEqual(upgrade(self.engine,apply=True),[])
        with self.engine.begin() as connection:
            self.assertEqual(connection.execute(text("SELECT * FROM reservations ORDER BY id")).all(),before)
            connection.execute(text("INSERT INTO reservations VALUES (2,NULL,NULL)"))
            connection.execute(text("INSERT INTO reservations VALUES (3,:note,:review)"),{"note":None,"review":"审"*500})
            self.assertEqual(connection.execute(text("SELECT LENGTH(review_note) FROM reservations WHERE id=3")).scalar(),1500)
