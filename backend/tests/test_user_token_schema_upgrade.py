"""Additive login-version upgrades preserve existing accounts and passwords."""

import os
import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models.users import User
from scripts.upgrade_user_token_version import upgrade
from tests import test_loan_mysql as fixtures


class UserTokenSchemaUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)

    def test_preview_apply_and_repeat_preserve_existing_accounts(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)"))
            connection.execute(text("INSERT INTO users VALUES (1, 'existing_reader', 'unchanged_hash')"))
        self.assertEqual(len(upgrade(self.engine)), 1)
        self.assertNotIn("token_version", {c["name"] for c in inspect(self.engine).get_columns("users")})
        self.assertEqual(len(upgrade(self.engine, apply=True)), 1)
        self.assertEqual(upgrade(self.engine, apply=True), [])
        with self.engine.begin() as connection:
            self.assertEqual(connection.execute(text("SELECT * FROM users")).one(),
                (1, "existing_reader", "unchanged_hash", 0))
            connection.execute(text("INSERT INTO users (id, username, password) VALUES (2, 'new_reader', 'new_hash')"))
            self.assertEqual(connection.execute(text("SELECT token_version FROM users WHERE id=2")).scalar(), 0)
            connection.execute(text("UPDATE users SET token_version=3 WHERE id=1"))
        self.assertEqual(upgrade(self.engine, apply=True), [])
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT token_version FROM users WHERE id=1")).scalar(), 3)

    def test_missing_users_table_is_not_created_implicitly(self):
        with self.assertRaisesRegex(RuntimeError, "users"):
            upgrade(self.engine, apply=True)
        self.assertFalse(inspect(self.engine).has_table("users"))

    def test_incompatible_existing_column_is_rejected_without_changes(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, token_version TEXT)"))
            connection.execute(text("INSERT INTO users VALUES (1, 'invalid')"))
        with self.assertRaisesRegex(RuntimeError, "token_version"):
            upgrade(self.engine, apply=True)
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT token_version FROM users")).scalar(), "invalid")

    def test_new_database_has_nonnullable_version_and_server_default(self):
        Base.metadata.create_all(self.engine)
        self.assertEqual(upgrade(self.engine), [])
        column = next(c for c in inspect(self.engine).get_columns("users") if c["name"] == "token_version")
        self.assertFalse(column["nullable"])
        self.assertIsNotNone(column["default"])
        with Session(self.engine) as db:
            user = User(username="fresh_reader", password="hash", name="reader", role="student")
            db.add(user)
            db.commit()
            self.assertEqual(user.token_version, 0)


@unittest.skipUnless(os.environ.get("MYSQL_LIBRARY_TEST_URL") or os.environ.get("RUN_LIBRARY_MYSQL_TEST") == "1",
    "需显式启用独立 MySQL 临时库升级测试")
class UserTokenSchemaUpgradeMySQLTest(unittest.TestCase):
    setUpClass = classmethod(fixtures.LoanMySQLConcurrencyTest.setUpClass.__func__)
    dispose_test_database = classmethod(fixtures.LoanMySQLConcurrencyTest.dispose_test_database.__func__)

    def test_mysql_upgrade_preserves_every_existing_column_and_nonzero_versions(self):
        with Session(self.engine) as db:
            db.add(User(username="old_reader", password="original_hash", name="原读者", role="student"))
            db.commit()
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE users DROP COLUMN token_version"))
            before = connection.execute(text("SELECT * FROM users ORDER BY id")).all()
        self.assertEqual(len(upgrade(self.engine)), 1)
        self.assertEqual(len(upgrade(self.engine, apply=True)), 1)
        with self.engine.begin() as connection:
            after = connection.execute(text("SELECT * FROM users ORDER BY id")).all()
            self.assertEqual([tuple(row[:-1]) for row in after], [tuple(row) for row in before])
            self.assertEqual(after[0][-1], 0)
            connection.execute(text("UPDATE users SET token_version=4"))
        self.assertEqual(upgrade(self.engine, apply=True), [])
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT token_version FROM users")).scalar(), 4)
