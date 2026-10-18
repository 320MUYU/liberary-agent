import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models
from app.models.users import User
from app.models.conversation import Conversation, ConversationTurn
from app.schemas.conversation import SendMessage
from scripts.upgrade_agent_conversations import upgrade


class ConversationModelsTest(unittest.TestCase):
    def test_message_protocol_rejects_identity_actions_and_blank_text(self):
        message = {"request_id": "3409794d-fca5-4151-96f1-e029c554aace", "text": "找书"}
        self.assertEqual(SendMessage(**message).hint, "auto")
        for changed in ({"user_id": 99}, {"confirmed": True}, {"text": "  "},
                {"hint": "admin"}, {"text": "字" * 1001}):
            with self.assertRaises(ValidationError):
                SendMessage.model_validate({**message, **changed})

    def test_upgrade_is_additive_repeatable_and_turn_replay_has_one_identity(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        User.__table__.create(engine)
        with Session(engine) as db:
            db.add(User(username="old", password="hash", name="旧用户", role="student"))
            db.commit()
        self.assertEqual(len(upgrade(engine)), 2)
        self.assertFalse(inspect(engine).has_table("agent_conversations"))
        self.assertEqual(len(upgrade(engine, apply=True)), 2)
        self.assertEqual(upgrade(engine, apply=True), [])
        with Session(engine) as db:
            self.assertEqual(db.execute(text("SELECT name FROM users")).scalar(), "旧用户")
            db.add(Conversation(conversation_id="conversation", user_id=1))
            db.commit()
            db.add(ConversationTurn(conversation_id="conversation", request_id="request", request={"text": "找书"}))
            db.commit()
            db.add(ConversationTurn(conversation_id="conversation", request_id="request", request={"text": "预约"}))
            with self.assertRaises(IntegrityError):
                db.commit()
