import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from app.agent import conversation
from app.common.exceptions import BusinessException
from app.models.conversation import Conversation, ConversationTurn
from app.models.workflow import WorkflowRun
from app.schemas.conversation import ConversationDecision, SendMessage
from tests import test_loan_service as fixtures


class ConversationRuntimeTest(unittest.TestCase):
    setUp = fixtures.LoanServiceTest.setUp
    add_book = fixtures.LoanServiceTest.add_book

    def create(self):
        return conversation.create(self.db, self.reader.id, str(uuid4()))["conversation_id"]

    def send(self, cid, text="找Python书", request_id=None):
        return conversation.send(self.db, self.reader.id, cid,
            SendMessage(request_id=request_id or uuid4(), text=text))

    def test_ask_replay_and_conflicting_or_cross_user_requests(self):
        cid = self.create(); rid = uuid4()
        with patch("app.agent.conversation.route_conversation", return_value=ConversationDecision(
                action="ask", message="需要找书还是空间？")) as route:
            first = self.send(cid, request_id=rid)
            self.assertEqual(self.send(cid, request_id=rid)["turns"], first["turns"])
            self.assertEqual(route.call_count, 1)
            with self.assertRaises(BusinessException):
                self.send(cid, "不同内容", rid)
        self.assertEqual(len(first["turns"]), 1)
        with self.assertRaises(BusinessException):
            conversation.view(self.db, self.other.id, cid)

    def test_plan_survives_lost_response_and_history_is_server_owned(self):
        cid = self.create(); rid = uuid4()
        decision = ConversationDecision(action="plan", plan={"steps": [
            {"task_type": "borrow", "title": "查库存", "query": "Python", "read_only": True}]})
        with patch("app.agent.conversation.route_conversation", return_value=decision) as route:
            with patch("app.agent.conversation.workflow.create_workflow", side_effect=BusinessException("丢失响应", 503)):
                with self.assertRaises(BusinessException):
                    self.send(cid, request_id=rid)
            with patch("app.agent.workflow.invoke_specialist", return_value={"status": "select_book", "books": [{"id": 1, "title": "Python"}]}):
                result = self.send(cid, request_id=rid)
            self.assertEqual(route.call_count, 1)
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["status"], "completed")
        with patch("app.agent.conversation.route_conversation", return_value=ConversationDecision(action="ask", message="请选择具体操作")) as route:
            self.send(cid, "第二本呢")
        self.assertIn("找Python书", str(route.call_args.args))
        self.assertIn("Python", str(route.call_args.args))
        self.assertEqual(self.db.query(WorkflowRun).count(), 1)

    def test_lease_blocks_overlap_and_foreign_task_cannot_be_attached(self):
        cid = self.create()
        row = self.db.query(Conversation).filter_by(conversation_id=cid).one()
        row.lease_until = datetime.now() + timedelta(minutes=2); self.db.commit()
        with self.assertRaises(BusinessException):
            self.send(cid)
        row.lease_until = None; self.db.commit()
        with patch("app.agent.conversation.route_conversation", return_value=ConversationDecision(
                action="conditions", workflow_id=uuid4(), draft={"people": 3})):
            with self.assertRaises(BusinessException):
                self.send(cid)
        self.assertEqual(self.db.query(ConversationTurn).one().status, "failed")
