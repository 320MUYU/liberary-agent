from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from tests import test_reservation as fixtures
from app.agent import reservation_actions as actions
from app.agent.policy import RunBudget
from app.agent.tools import execute_read_tool, tool_definitions
from app.common.exceptions import BusinessException
from app.models.agent import AgentReservationAction
from app.models.reservations import Reservation
from app.schemas.reservation import ReservationReviewRequest
from app.services import reservation_service
from app.services.space_discovery import SpaceConditions


class AgentReservationActionsTest(unittest.TestCase):
    setUp = fixtures.ReservationFlowTest.setUp
    tearDown = fixtures.ReservationFlowTest.tearDown
    request = fixtures.ReservationFlowTest.request

    def conditions(self):
        return SpaceConditions.model_validate(self.request().model_dump(exclude={"lab_id"}))

    def prepare(self, run="space-run"):
        return actions.prepare_reservation(self.db, self.student.id, run, self.lab.id, self.conditions())

    def test_prepare_confirm_replay_and_admin_progress(self):
        preview = self.prepare()
        self.assertEqual(preview["space"]["id"], self.lab.id)
        self.assertEqual(preview["conditions"]["people"], 3)
        self.assertEqual(self.db.query(Reservation).count(), 0)
        receipt = actions.decide_reservation(self.db, self.student.id, preview["id"], True)
        self.assertEqual(receipt["status"], "reservation_pending")
        self.assertEqual(actions.decide_reservation(self.db, self.student.id, preview["id"], True), receipt)
        reservation_service.review_reservation(self.db, self.admin, receipt["reservation_id"], ReservationReviewRequest(status="approved"))
        self.assertEqual(actions.decide_reservation(self.db, self.student.id, preview["id"], True)["status"], "reservation_approved")
        self.assertEqual(self.db.query(Reservation).count(), 1)

    def test_cancel_expiry_identity_and_disabled_account(self):
        preview = self.prepare()
        with self.assertRaises(BusinessException):
            actions.decide_reservation(self.db, self.other.id, preview["id"], True)
        self.assertEqual(actions.decide_reservation(self.db, self.student.id, preview["id"], False)["status"], "cancelled")
        with self.assertRaises(BusinessException):
            actions.decide_reservation(self.db, self.student.id, preview["id"], True)
        preview = self.prepare("expired")
        self.db.query(AgentReservationAction).filter_by(action_id=preview["id"]).one().expires_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaises(BusinessException):
            actions.decide_reservation(self.db, self.student.id, preview["id"], True)
        preview = self.prepare("disabled")
        self.student.status = 0
        self.db.commit()
        with self.assertRaises(BusinessException):
            actions.decide_reservation(self.db, self.student.id, preview["id"], True)
        self.assertEqual(self.db.query(Reservation).count(), 0)

    def test_snapshot_and_new_approved_conflict_block_confirmation(self):
        preview = self.prepare()
        self.lab.capacity = 4
        self.db.commit()
        with self.assertRaises(BusinessException):
            actions.decide_reservation(self.db, self.student.id, preview["id"], True)
        preview = self.prepare("conflict")
        other = reservation_service.create_reservation(self.db, self.other, self.request())
        reservation_service.review_reservation(self.db, self.admin, other.id, ReservationReviewRequest(status="approved"))
        with self.assertRaises(BusinessException):
            actions.decide_reservation(self.db, self.student.id, preview["id"], True)
        self.assertEqual(self.db.query(Reservation).count(), 1)

    def test_rollback_then_different_tasks_share_one_existing_application(self):
        first = self.prepare("first")
        second = self.prepare("second")
        original = reservation_service.create_reservation_in_transaction
        def fail(*args):
            original(*args)
            raise RuntimeError("injected failure")
        with patch.object(reservation_service, "create_reservation_in_transaction", side_effect=fail):
            with self.assertRaises(RuntimeError):
                actions.decide_reservation(self.db, self.student.id, first["id"], True)
        self.assertEqual(self.db.query(Reservation).count(), 0)
        one = actions.decide_reservation(self.db, self.student.id, first["id"], True)
        two = actions.decide_reservation(self.db, self.student.id, second["id"], True)
        self.assertEqual(one, two)
        self.assertEqual(self.db.query(Reservation).count(), 1)

    def test_read_tools_are_scoped_strict_and_budgeted(self):
        args = {"conditions": self.conditions().model_dump(mode="json")}
        budget = RunBudget(max_tools=1)
        result = execute_read_tool(self.db, self.student.id, "search_spaces", args, budget)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["spaces"][0]["id"], self.lab.id)
        self.assertEqual(execute_read_tool(self.db, self.student.id, "search_spaces", args, budget)["error_code"], "budget_exceeded")
        self.assertEqual(execute_read_tool(self.db, self.student.id, "search_spaces", {**args, "user_id": 1}, RunBudget())["error_code"], "invalid_arguments")
        self.assertEqual({tool["name"] for tool in tool_definitions("reservation")}, {"search_spaces", "get_space"})
        self.assertEqual(self.db.query(Reservation).count(), 0)
