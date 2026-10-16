import unittest
from sqlalchemy import create_engine, inspect, text
from scripts.upgrade_agent_returns import upgrade


class AgentSchemaUpgradeTest(unittest.TestCase):
    def test_dry_run_additive_upgrade_defaults_and_repeat(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE agent_runs (id INTEGER PRIMARY KEY, query VARCHAR(1000))"))
            connection.execute(text("CREATE TABLE agent_actions (id INTEGER PRIMARY KEY, snapshot TEXT)"))
            connection.execute(text("INSERT INTO agent_runs VALUES (1, 'old query')"))
            connection.execute(text("INSERT INTO agent_actions VALUES (1, 'old snapshot')"))
        self.assertEqual(len(upgrade(engine)), 2)
        self.assertNotIn("task_type", {c["name"] for c in inspect(engine).get_columns("agent_runs")})
        self.assertEqual(len(upgrade(engine, apply=True)), 2)
        self.assertEqual(upgrade(engine, apply=True), [])
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT query, task_type FROM agent_runs")).one(), ("old query", "borrow"))
            self.assertEqual(connection.execute(text("SELECT snapshot, action_type FROM agent_actions")).one(), ("old snapshot", "borrow"))
