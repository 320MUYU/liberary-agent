import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent import conversation
from app.common.exceptions import BusinessException
from app.models.conversation import ConversationTurn
from app.schemas.conversation import ConversationDecision, SendMessage
from tests import test_loan_mysql as fixtures


@unittest.skipUnless(os.environ.get("RUN_LIBRARY_MYSQL_TEST") == "1" or os.environ.get("MYSQL_LIBRARY_TEST_URL"), "需启用独立MySQL会话并发测试")
class ConversationMySQLTest(unittest.TestCase):
    setUpClass = classmethod(fixtures.LoanMySQLConcurrencyTest.setUpClass.__func__)
    dispose_test_database = classmethod(fixtures.LoanMySQLConcurrencyTest.dispose_test_database.__func__)
    setUp = fixtures.LoanMySQLConcurrencyTest.setUp
    user = fixtures.LoanMySQLConcurrencyTest.user

    def test_overlapping_messages_are_serialized_and_replay_has_one_turn(self):
        user_id = self.reader.id
        cid = str(uuid4())
        conversation.create(self.db, user_id, cid)
        entered = Event(); release = Event()
        message = SendMessage(request_id=uuid4(), text="请问需要什么信息")
        def route(*_):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("并发测试未释放")
            return ConversationDecision(action="ask", message="请说明需要的帮助")
        def send():
            with Session(self.engine) as db:
                return conversation.send(db, user_id, cid, message)
        with patch("app.agent.conversation.route_conversation", side_effect=route) as model:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(send)
                self.assertTrue(entered.wait(10))
                try:
                    with self.assertRaises(BusinessException) as error:
                        send()
                    self.assertEqual(error.exception.code, 409)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10)["turns"][0]["status"], "completed")
            replay = send()
            self.assertEqual(len(replay["turns"]), 1)
            self.assertEqual(model.call_count, 1)
        with Session(self.engine) as db:
            self.assertEqual(db.query(ConversationTurn).filter_by(conversation_id=cid).count(), 1)
