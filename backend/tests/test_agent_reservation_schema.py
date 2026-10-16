import unittest
from sqlalchemy import create_engine, inspect, text

import app.models
from app.database import Base
from app.models.agent import AgentReservationAction
from app.models.users import User
from scripts.upgrade_agent_reservations import upgrade


class AgentReservationSchemaTest(unittest.TestCase):
    def test_only_new_table_created_and_old_records_preserved(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table is not AgentReservationAction.__table__])
        with engine.begin() as connection:
            connection.execute(User.__table__.insert().values(id=1,username="old",password="hash",name="旧账号",role="student",status=1))
        def signature(name):
            return [(column["name"],str(column["type"]),column["nullable"],column["default"])
                for column in inspect(engine).get_columns(name)]
        before = {name: signature(name) for name in inspect(engine).get_table_names()}
        self.assertEqual(len(upgrade(engine)),1)
        self.assertNotIn("agent_reservation_actions",inspect(engine).get_table_names())
        self.assertEqual(len(upgrade(engine,apply=True)),1)
        self.assertEqual(upgrade(engine,apply=True),[])
        for name, columns in before.items():
            self.assertEqual(signature(name),columns)
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT username FROM users WHERE id=1")).scalar(),"old")
