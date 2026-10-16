from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from tests import test_reservation as fixtures
from app.common.exceptions import BusinessException
from app.models.equipments import Equipment
from app.models.reservations import Reservation
from app.schemas.reservation import ReservationReviewRequest
from app.services import reservation_service
from app.services.space_discovery import SpaceConditions, discover_spaces, get_space


class SpaceDiscoveryTest(unittest.TestCase):
    setUp = fixtures.ReservationFlowTest.setUp
    tearDown = fixtures.ReservationFlowTest.tearDown
    request = fixtures.ReservationFlowTest.request

    def conditions(self, **changes):
        return SpaceConditions(date=self.day, start="14:00", end="16:00", people=3,
            purpose="课程讨论", **changes)

    def test_metadata_and_equipment_search_never_exposes_other_reservations_or_writes(self):
        self.db.add(Equipment(lab_id=self.lab.id, name="投影仪", total=1, available=1))
        self.db.commit()
        for keyword in ["研讨", "A-101", "A 楼", "投影仪"]:
            result = discover_spaces(self.db, self.conditions(), keyword=keyword)
            self.assertEqual(result["spaces"][0]["id"], self.lab.id)
            self.assertTrue(result["spaces"][0]["can_reserve"])
            self.assertIn("checked_at", result)
            self.assertNotIn("applicant", str(result))
        self.assertEqual(self.db.query(Reservation).count(), 0)

    def test_pending_does_not_occupy_and_approved_overlap_does(self):
        pending = reservation_service.create_reservation(self.db, self.other, self.request())
        self.assertTrue(get_space(self.db, self.conditions(), self.lab.id)["spaces"][0]["can_reserve"])
        reservation_service.review_reservation(self.db, self.admin, pending.id, ReservationReviewRequest(status="approved"))
        busy = get_space(self.db, self.conditions(), self.lab.id)["spaces"][0]
        self.assertFalse(busy["can_reserve"])
        self.assertIn("approved_conflict", busy["unavailable_reasons"])
        self.assertNotIn(self.other.username, str(busy))
        adjacent = self.conditions().model_copy(update={"start": "16:00", "end": "17:00"})
        self.assertTrue(get_space(self.db, adjacent, self.lab.id)["spaces"][0]["can_reserve"])

    def test_capacity_maintenance_and_current_busy_status_are_distinct(self):
        self.lab.capacity = 2
        self.lab.status = "maintenance"
        self.db.commit()
        room = get_space(self.db, self.conditions(), self.lab.id)["spaces"][0]
        self.assertEqual(set(room["unavailable_reasons"]), {"capacity", "maintenance"})
        self.lab.capacity = 5
        self.lab.status = "busy"
        self.db.commit()
        self.assertTrue(get_space(self.db, self.conditions(), self.lab.id)["spaces"][0]["can_reserve"])

    def test_two_hour_boundary_and_strict_conditions(self):
        fixed = datetime.combine(self.day, datetime.strptime("12:00", "%H:%M").time())
        conditions = self.conditions()
        with patch("app.services.space_discovery.datetime") as clock:
            clock.now.return_value = fixed
            clock.combine = datetime.combine
            clock.strptime = datetime.strptime
            self.assertTrue(get_space(self.db, conditions, self.lab.id)["spaces"][0]["can_reserve"])
            clock.now.return_value = fixed + timedelta(seconds=1)
            self.assertFalse(get_space(self.db, conditions, self.lab.id)["spaces"][0]["can_reserve"])
        valid = self.conditions().model_dump()
        for change in [{"start": "16:00"}, {"people": True}, {"purpose": " "}, {"user_id": 1}, {"start": "25:00"}]:
            with self.assertRaises(ValidationError):
                SpaceConditions.model_validate({**valid, **change})

    def test_transaction_helper_does_not_commit_and_rolls_back(self):
        row = reservation_service.create_reservation_in_transaction(self.db, self.student, self.request())
        self.assertIsNotNone(row.id)
        self.db.rollback()
        self.assertEqual(self.db.query(Reservation).count(), 0)
        self.student.status = 0
        self.db.commit()
        with self.assertRaises(BusinessException):
            reservation_service.create_reservation(self.db, self.student, self.request())
        self.assertFalse(self.db.in_transaction())

    def test_stale_room_in_session_is_refreshed_before_creation(self):
        from sqlalchemy import update
        self.db.execute(update(type(self.lab)).where(type(self.lab).id == self.lab.id).values(status="maintenance"),
            execution_options={"synchronize_session": False})
        with self.assertRaises(BusinessException):
            reservation_service.create_reservation(self.db, self.student, self.request())
        self.assertFalse(self.db.in_transaction())
