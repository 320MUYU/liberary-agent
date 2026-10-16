from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_loan_service as fixtures
from app.agent import actions
from app.common.exceptions import BusinessException
from app.models.agent import AgentAction
from app.schemas.loan import BorrowConfirmRequest, LoanRequest, LoanRejectRequest
from app.services import loan_service, book_service


class AgentReturnActionsTest(unittest.TestCase):
    setUp = fixtures.LoanServiceTest.setUp
    add_book = fixtures.LoanServiceTest.add_book

    def borrowed(self):
        loan = loan_service.create_loan(self.db, self.reader, LoanRequest(book_id=self.book.id))
        return loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest())

    def test_preview_confirmation_and_replay_preserve_occupied_copy(self):
        loan = self.borrowed()
        action = actions.prepare_return(self.db, self.reader.id, "return-run", loan.id)
        self.assertEqual(action["action_type"], "return")
        self.assertEqual(action["loan"]["id"], loan.id)
        self.assertEqual(self.db.get(type(loan), loan.id).status, "borrowed")
        first = actions.decide_return(self.db, self.reader.id, action["id"], True)
        requested_at = loan.return_requested_at
        self.assertEqual(first["status"], "return_pending")
        self.assertEqual(actions.decide_return(self.db, self.reader.id, action["id"], True), first)
        self.assertEqual(loan.return_requested_at, requested_at)
        self.assertEqual(loan.active_copy_id, self.copy.id)
        self.assertEqual(book_service.get_book_detail(self.db, self.book.id).available_copies, 0)
        loan_service.confirm_return(self.db, self.admin, loan.id)
        self.assertEqual(actions.decide_return(self.db, self.reader.id, action["id"], True)["status"], "returned")

    def test_cancel_expiry_ownership_and_action_kind(self):
        loan = self.borrowed()
        with self.assertRaises(BusinessException):
            actions.prepare_return(self.db, self.other.id, "foreign", loan.id)
        action = actions.prepare_return(self.db, self.reader.id, "cancel", loan.id)
        with self.assertRaises(BusinessException):
            actions.decide_return(self.db, self.other.id, action["id"], True)
        with self.assertRaises(BusinessException):
            actions.decide_borrow(self.db, self.reader.id, action["id"], True)
        self.assertEqual(actions.decide_return(self.db, self.reader.id, action["id"], False)["status"], "cancelled")
        with self.assertRaises(BusinessException):
            actions.decide_return(self.db, self.reader.id, action["id"], True)
        another = actions.prepare_return(self.db, self.reader.id, "expired", loan.id)
        self.db.query(AgentAction).filter_by(action_id=another["id"]).one().expires_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaises(BusinessException):
            actions.decide_return(self.db, self.reader.id, another["id"], True)
        self.assertEqual(loan.status, "borrowed")

    def test_pending_loan_rejected_and_downlisted_book_can_be_returned(self):
        loan = loan_service.create_loan(self.db, self.reader, LoanRequest(book_id=self.book.id))
        with self.assertRaises(BusinessException):
            actions.prepare_return(self.db, self.reader.id, "pending", loan.id)
        loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest())
        self.book.is_active = False
        self.db.commit()
        action = actions.prepare_return(self.db, self.reader.id, "downlisted", loan.id)
        self.assertEqual(actions.decide_return(self.db, self.reader.id, action["id"], True)["status"], "return_pending")

    def test_business_change_and_receipt_roll_back_together(self):
        loan = self.borrowed()
        action = actions.prepare_return(self.db, self.reader.id, "rollback", loan.id)
        original = loan_service.request_return_in_transaction
        def failing(*args):
            original(*args)
            raise RuntimeError("injected return failure")
        with patch.object(loan_service, "request_return_in_transaction", side_effect=failing):
            with self.assertRaises(RuntimeError):
                actions.decide_return(self.db, self.reader.id, action["id"], True)
        self.assertEqual(loan.status, "borrowed")
        self.assertEqual(self.db.query(AgentAction).one().status, "prepared")
        self.assertEqual(actions.decide_return(self.db, self.reader.id, action["id"], True)["status"], "return_pending")

    def test_existing_page_return_and_disabled_account_are_checked(self):
        loan = self.borrowed()
        action = actions.prepare_return(self.db, self.reader.id, "page-race", loan.id)
        loan_service.request_return(self.db, self.reader, loan.id)
        requested_at = loan.return_requested_at
        self.assertEqual(actions.decide_return(self.db, self.reader.id, action["id"], True)["status"], "return_pending")
        self.assertEqual(loan.return_requested_at, requested_at)
        self.reader.status = 0
        self.db.commit()
        with self.assertRaises(BusinessException):
            actions.decide_return(self.db, self.reader.id, action["id"], True)

    def test_fixed_status_cases_only_borrowed_can_prepare(self):
        cases = json.loads((Path(__file__).parent / "fixtures/agent_returns.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(status=case["status"]):
                book, _ = self.add_book(barcode="STATUS-" + case["status"])
                self.db.commit()
                loan = loan_service.create_loan(self.db, self.reader, LoanRequest(book_id=book.id))
                if case["status"] in {"borrowed", "return_pending", "returned"}:
                    loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest())
                if case["status"] in {"return_pending", "returned"}:
                    loan_service.request_return(self.db, self.reader, loan.id)
                if case["status"] == "returned":
                    loan_service.confirm_return(self.db, self.admin, loan.id)
                if case["status"] == "rejected":
                    loan_service.reject_loan(self.db, self.admin, loan.id, LoanRejectRequest(reason="固定用例"))
                if case["status"] == "cancelled":
                    loan_service.cancel_loan(self.db, self.reader, loan.id)
                if case["can_return"]:
                    result = actions.prepare_return(self.db, self.reader.id, case["status"], loan.id)
                    self.assertEqual(result["loan"]["id"], loan.id)
                else:
                    with self.assertRaises(BusinessException):
                        actions.prepare_return(self.db, self.reader.id, case["status"], loan.id)

    def test_snapshot_change_and_non_boolean_confirmation_never_write(self):
        loan = self.borrowed()
        action = actions.prepare_return(self.db, self.reader.id, "snapshot", loan.id)
        for value in [1, "true", None]:
            with self.assertRaises(BusinessException):
                actions.decide_return(self.db, self.reader.id, action["id"], value)
        loan.due_at += timedelta(days=1)
        self.db.commit()
        with self.assertRaises(BusinessException):
            actions.decide_return(self.db, self.reader.id, action["id"], True)
        self.assertEqual(loan.status, "borrowed")
        self.assertIsNone(loan.return_requested_at)
        self.assertEqual(self.db.query(AgentAction).one().status, "prepared")
