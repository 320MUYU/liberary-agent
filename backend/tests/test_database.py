import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import database


class DatabaseBootstrapTest(unittest.TestCase):
    @patch.object(database, "create_engine")
    def test_new_mysql_database_connects_to_server_without_selecting_missing_schema(self, create_engine):
        server = MagicMock()
        create_engine.return_value = server
        config = SimpleNamespace(DATABASE_URL="mysql+pymysql://tester:password@localhost/new_library")
        with patch.object(database, "settings", config):
            database.create_database_if_not_exists()

        url = create_engine.call_args.args[0]
        self.assertIsNone(url.database)
        self.assertEqual(url.username, "tester")
        self.assertEqual(url.host, "localhost")
        sql = server.connect.return_value.__enter__.return_value.execute.call_args.args[0]
        self.assertIn("CREATE DATABASE IF NOT EXISTS `new_library`", str(sql))
        server.dispose.assert_called_once()

    @patch.object(database, "create_engine")
    def test_sqlite_does_not_attempt_server_database_creation(self, create_engine):
        with patch.object(database, "settings", SimpleNamespace(DATABASE_URL="sqlite:///:memory:")):
            database.create_database_if_not_exists()
        create_engine.assert_not_called()

    @patch.object(database, "create_engine")
    def test_invalid_database_name_is_rejected_before_connecting(self, create_engine):
        config = SimpleNamespace(DATABASE_URL="mysql+pymysql://tester:password@localhost/invalid-name")
        with patch.object(database, "settings", config), self.assertRaises(ValueError):
            database.create_database_if_not_exists()
        create_engine.assert_not_called()

    @patch.object(database, "create_engine")
    def test_server_engine_is_disposed_when_connection_fails(self, create_engine):
        server = create_engine.return_value
        server.connect.side_effect = RuntimeError("connection unavailable")
        config = SimpleNamespace(DATABASE_URL="mysql+pymysql://tester:password@localhost/new_library")
        with patch.object(database, "settings", config), self.assertRaises(RuntimeError):
            database.create_database_if_not_exists()
        server.dispose.assert_called_once()
