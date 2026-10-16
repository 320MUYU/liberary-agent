import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests import test_loan_service as fixtures
from app.agent.actions import prepare_borrow, decide_borrow
from app.common.exceptions import BusinessException
from app.models.agent import AgentAction
from app.models.loans import Loan
from app.services import loan_service


class AgentActionsTest(unittest.TestCase):
    setUp = fixtures.LoanServiceTest.setUp
    add_book = fixtures.LoanServiceTest.add_book

    def prepare(self, run_id="test-run"):
        return prepare_borrow(self.db, self.reader.id, run_id, self.book.id)

    def test_prepare_does_not_write_loan_and_confirmation_is_idempotent(self):
        action = self.prepare()
        self.assertEqual(self.db.query(Loan).count(), 0)
        first = decide_borrow(self.db, self.reader.id, action["id"], True)
        second = decide_borrow(self.db, self.reader.id, action["id"], True)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "pending")
        self.assertEqual(self.db.query(Loan).count(), 1)
        self.assertIsNone(self.db.query(Loan).one().active_copy_id)

    def test_cancel_expiry_and_cross_user_cannot_submit(self):
        action = self.prepare()
        with self.assertRaises(BusinessException):
            decide_borrow(self.db, self.other.id, action["id"], True)
        self.assertEqual(decide_borrow(self.db, self.reader.id, action["id"], False)["status"], "cancelled")
        with self.assertRaises(BusinessException):
            decide_borrow(self.db, self.reader.id, action["id"], True)
        another = self.prepare("another-run")
        record = self.db.query(AgentAction).filter_by(action_id=another["id"]).one()
        record.expires_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaises(BusinessException):
            decide_borrow(self.db, self.reader.id, another["id"], True)
        self.assertEqual(self.db.query(Loan).count(), 0)

    def test_rechecks_inventory_and_book_snapshot(self):
        action = self.prepare()
        self.book.title = "新版书名"
        self.db.commit()
        with self.assertRaises(BusinessException):
            decide_borrow(self.db, self.reader.id, action["id"], True)
        self.assertEqual(self.db.query(Loan).count(), 0)

    def test_receipt_and_loan_roll_back_together(self):
        action = self.prepare()
        original = loan_service.create_loan_in_transaction
        def fail(*args):
            original(*args)
            raise RuntimeError("injected crash after loan flush")
        with patch.object(loan_service, "create_loan_in_transaction", side_effect=fail):
            with self.assertRaises(RuntimeError):
                decide_borrow(self.db, self.reader.id, action["id"], True)
        self.assertEqual(self.db.query(Loan).count(), 0)
        self.assertEqual(self.db.query(AgentAction).one().status, "prepared")
        self.assertEqual(decide_borrow(self.db, self.reader.id, action["id"], True)["status"], "pending")
