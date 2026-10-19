import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import app.models
from app.models.users import User
from scripts.upgrade_reader_notifications import upgrade


class NotificationSchemaUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        User.__table__.create(self.engine)

    def test_preview_apply_and_repeat_leave_accounts_untouched(self):
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (username,password,name,role,status,create_time,update_time) "
                "VALUES ('existing','original_hash','读者','student',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            before = connection.execute(text("SELECT * FROM users")).all()
        statements = upgrade(self.engine)
        self.assertTrue(any("CREATE TABLE" in statement for statement in statements))
        self.assertFalse(inspect(self.engine).has_table("reader_notifications"))
        self.assertTrue(upgrade(self.engine, apply=True))
        self.assertEqual(upgrade(self.engine, apply=True), [])
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT * FROM users")).all(), before)
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM reader_notifications")).scalar(), 0)
        indexes = inspect(self.engine).get_indexes("reader_notifications")
        self.assertTrue(any(i["column_names"][:2] == ["user_id", "read_at"] for i in indexes))

    def test_missing_users_table_does_not_create_partial_schema(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with self.assertRaisesRegex(RuntimeError, "users"):
            upgrade(engine, apply=True)
        self.assertEqual(inspect(engine).get_table_names(), [])

    def test_existing_incompatible_table_is_not_silently_accepted(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE reader_notifications (id INTEGER PRIMARY KEY)"))
        with self.assertRaisesRegex(RuntimeError, "reader_notifications"):
            upgrade(self.engine, apply=True)

    def test_event_key_is_unique_per_recipient(self):
        from sqlalchemy.orm import Session
        from app.models.notification import Notification
        upgrade(self.engine, apply=True)
        with Session(self.engine) as db:
            for user in (1, 2):
                db.add(Notification(user_id=user, event_key="loan:1:borrowed", kind="loan_borrowed", title="借出",
                    content="内容", resource_type="loan", resource_id=1))
            db.commit()
            db.add(Notification(user_id=1, event_key="loan:1:borrowed", kind="loan_borrowed", title="重复",
                content="内容", resource_type="loan", resource_id=1))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
