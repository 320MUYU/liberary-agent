import unittest
from datetime import date, timedelta, time

from pydantic import ValidationError

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.admin import admin_list_reservations, delete_lab, review_reservation
from app.api.reservation import cancel_reservation, create_reservation, my_reservations
from app.common.exceptions import BusinessException
from app.database import Base
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.models.users import User
from app.schemas.reservation import ReservationCreateRequest, ReservationReviewRequest, ReservationResponse


class ReservationFlowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.student = User(username="student", password="hash", name="学生", role="student")
        self.other = User(username="other", password="hash", name="其他学生", role="student")
        self.admin = User(username="admin", password="hash", name="管理员", role="admin")
        self.lab = Lab(
            name="测试研讨室",
            code="A-101",
            building="A 楼",
            floor="1",
            capacity=5,
            category="综合",
            status="available",
        )
        self.db.add_all([self.student, self.other, self.admin, self.lab])
        self.db.commit()
        self.day = date.today() + timedelta(days=1)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, start="14:00", end="16:00", people=3):
        return ReservationCreateRequest(
            lab_id=self.lab.id,
            date=self.day,
            start=start,
            end=end,
            people=people,
            purpose="课程讨论",
        )

    def test_submit_review_conflict_and_cancel(self):
        first = create_reservation(self.request(), self.student, self.db).data
        self.assertEqual(first.status, "pending")
        self.assertEqual(first.lab_name, "测试研讨室")

        listing = admin_list_reservations(
            page=1, page_size=10, status="pending", keyword="学生", _=self.admin, db=self.db
        ).data
        self.assertEqual(listing.total, 1)
        self.assertEqual(listing.items[0].id, first.id)

        approved = review_reservation(
            first.id, ReservationReviewRequest(status="approved"), self.admin, self.db
        ).data
        self.assertEqual(approved.status, "approved")

        with self.assertRaises(BusinessException) as conflict:
            create_reservation(self.request(start="15:00", end="17:00"), self.other, self.db)
        self.assertEqual(conflict.exception.code, 409)

        second = create_reservation(self.request(start="16:00", end="17:00"), self.other, self.db).data
        with self.assertRaises(BusinessException) as denied:
            cancel_reservation(second.id, self.student, self.db)
        self.assertEqual(denied.exception.code, 404)

        cancelled = cancel_reservation(second.id, self.other, self.db).data
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(len(my_reservations(self.other, self.db).data), 1)

        with self.assertRaises(BusinessException) as repeated:
            review_reservation(
                first.id,
                ReservationReviewRequest(status="rejected", review_note="重复处理"),
                self.admin,
                self.db,
            )
        self.assertEqual(repeated.exception.code, 409)

    def test_approval_checks_pending_overlap_and_preserves_lab(self):
        first = create_reservation(self.request(), self.student, self.db).data
        second = create_reservation(self.request(start="15:00", end="17:00"), self.other, self.db).data
        review_reservation(first.id, ReservationReviewRequest(status="approved"), self.admin, self.db)
        with self.assertRaises(BusinessException) as conflict:
            review_reservation(
                second.id, ReservationReviewRequest(status="approved"), self.admin, self.db
            )
        self.assertEqual(conflict.exception.code, 409)

        rejected = review_reservation(
            second.id,
            ReservationReviewRequest(status="rejected", review_note="该时段已占用"),
            self.admin,
            self.db,
        ).data
        self.assertEqual(rejected.review_note, "该时段已占用")

        with self.assertRaises(BusinessException) as protected:
            delete_lab(self.lab.id, self.admin, self.db)
        self.assertEqual(protected.exception.code, 409)

    def test_capacity_and_maintenance_validation(self):
        with self.assertRaises(BusinessException):
            create_reservation(self.request(people=6), self.student, self.db)
        self.lab.status = "maintenance"
        self.db.commit()
        with self.assertRaises(BusinessException):
            create_reservation(self.request(), self.student, self.db)

    def test_rejection_reason_and_two_hour_rules(self):
        with self.assertRaises(ValidationError):
            ReservationReviewRequest(status="rejected", review_note="   ")

        request = ReservationCreateRequest(
            lab_id=self.lab.id,
            date=date.today(),
            start="00:00",
            end="00:30",
            people=2,
            purpose="临时讨论",
        )
        with self.assertRaises(BusinessException) as too_late:
            create_reservation(request, self.student, self.db)
        self.assertIn("提前 2 小时", too_late.exception.message)

        approved = create_reservation(self.request(), self.student, self.db).data
        review_reservation(
            approved.id, ReservationReviewRequest(status="approved"), self.admin, self.db
        )
        reservation = self.db.query(Reservation).filter(Reservation.id == approved.id).one()
        reservation.date = date.today()
        reservation.start = "00:00"
        reservation.end = "00:30"
        self.db.commit()
        with self.assertRaises(BusinessException) as too_late_to_cancel:
            cancel_reservation(approved.id, self.student, self.db)
        self.assertIn("2 小时内", too_late_to_cancel.exception.message)

    def test_legacy_mysql_time_values_are_serialized_without_changing_storage(self):
        created = create_reservation(self.request(), self.student, self.db).data.model_dump()
        response = ReservationResponse.model_validate({**created,
            "start": timedelta(hours=14), "end": time(16, 0)})
        self.assertEqual((response.start,response.end),("14:00","16:00"))


if __name__ == "__main__":
    unittest.main()
