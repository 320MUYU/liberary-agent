from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import os
from threading import Barrier
import unittest
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests import test_loan_mysql as fixtures
from app.agent.reservation_actions import prepare_reservation, decide_reservation
from app.common.exceptions import BusinessException
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.models.users import User
from app.schemas.reservation import ReservationCreateRequest, ReservationReviewRequest
from app.services import reservation_service
from app.services.space_discovery import SpaceConditions


@unittest.skipUnless(os.environ.get("MYSQL_LIBRARY_TEST_URL") or os.environ.get("RUN_LIBRARY_MYSQL_TEST")=="1",
    "需显式启用独立 MySQL 临时库并发验收")
class ReservationMySQLConcurrencyTest(unittest.TestCase):
    setUpClass=classmethod(fixtures.LoanMySQLConcurrencyTest.setUpClass.__func__)
    dispose_test_database=classmethod(fixtures.LoanMySQLConcurrencyTest.dispose_test_database.__func__)
    setUp=fixtures.LoanMySQLConcurrencyTest.setUp
    user=fixtures.LoanMySQLConcurrencyTest.user

    def setup_space(self):
        room=Lab(name="并发空间验收",code=self.namespace,building="测试馆",floor="1",capacity=6,category="研讨室")
        self.db.add(room);self.db.commit()
        self.conditions=SpaceConditions(date=date.today()+timedelta(days=2),start="14:00",end="16:00",people=3,purpose="课程讨论")
        self.room_id=room.id
        self.reader_id=self.reader.id
        self.data=ReservationCreateRequest(lab_id=room.id,**self.conditions.model_dump())
        return prepare_reservation(self.db,self.reader_id,str(uuid4()),room.id,self.conditions)

    def race(self, first, second):
        self.db.commit()
        barrier=Barrier(2)
        def run(callback):
            with Session(self.engine) as db:
                db.execute(text("SET SESSION innodb_lock_wait_timeout=5"))
                # Exercise MySQL REPEATABLE READ with a snapshot older than the competing write.
                db.query(Reservation).count()
                barrier.wait(timeout=10)
                try:
                    return 200,callback(db)
                except BusinessException as exc:
                    return exc.code,None
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(run,callback) for callback in (first,second)]
            return [future.result(timeout=20) for future in futures]

    def assert_one(self):
        self.db.rollback()
        rows=self.db.query(Reservation).filter_by(applicant_id=self.reader_id,lab_id=self.room_id).all()
        self.assertEqual(len(rows),1)
        return rows[0]

    def test_same_action_returns_identical_committed_receipt_with_old_snapshots(self):
        action=self.setup_space()
        results=self.race(*[lambda db:decide_reservation(db,self.reader_id,action['id'],True)]*2)
        self.assertEqual([code for code,_ in results],[200,200])
        self.assertEqual(results[0][1],results[1][1])
        self.assert_one()

    def test_distinct_tasks_for_same_slot_reuse_one_application(self):
        first=self.setup_space()
        second=prepare_reservation(self.db,self.reader_id,str(uuid4()),self.room_id,self.conditions)
        results=self.race(lambda db:decide_reservation(db,self.reader_id,first['id'],True),
            lambda db:decide_reservation(db,self.reader_id,second['id'],True))
        self.assertEqual([code for code,_ in results],[200,200])
        self.assertEqual(results[0][1],results[1][1])
        self.assert_one()

    def test_agent_and_original_page_share_one_application(self):
        action=self.setup_space()
        results=self.race(lambda db:decide_reservation(db,self.reader_id,action['id'],True),
            lambda db:reservation_service.create_reservation(db,db.get(User,self.reader_id),self.data).id)
        self.assertEqual([code for code,_ in results],[200,200])
        row=self.assert_one()
        self.assertEqual(results[0][1]['reservation_id'],row.id)
        self.assertEqual(results[1][1],row.id)

    def test_agent_submission_and_admin_approval_cannot_create_approved_overlap(self):
        action=self.setup_space()
        other=reservation_service.create_reservation(self.db,self.other,self.data)
        other_id=other.id
        results=self.race(lambda db:decide_reservation(db,self.reader_id,action['id'],True),
            lambda db:reservation_service.review_reservation(db,db.get(User,self.admin_id),other_id,
                ReservationReviewRequest(status="approved")).id)
        self.assertEqual(results[1][0],200)
        self.assertIn(results[0][0],(200,409))
        self.db.rollback()
        if results[0][0]==200:
            with self.assertRaises(BusinessException):
                reservation_service.review_reservation(self.db,self.admin,results[0][1]['reservation_id'],ReservationReviewRequest(status="approved"))
            self.db.rollback()
        self.assertEqual(self.db.query(Reservation).filter_by(lab_id=self.room_id,status="approved").count(),1)
