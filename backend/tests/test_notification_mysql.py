"""Actual MySQL locking across concurrent reminder workers and return requests."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

from sqlalchemy.orm import Session

from tests import test_loan_mysql as fixtures
from app.models.notification import Notification
from app.models.loans import Loan
from app.models.users import User
from app.schemas.loan import BorrowConfirmRequest
from app.services import loan_service
from app.services.notification_reminders import generate_reminders
from scripts.upgrade_reader_notifications import upgrade


@unittest.skipUnless(os.environ.get('MYSQL_LIBRARY_TEST_URL') or os.environ.get('RUN_LIBRARY_MYSQL_TEST') == '1',
    'requires isolated MySQL database')
class NotificationMySQLTest(unittest.TestCase):
    setUpClass = classmethod(fixtures.LoanMySQLConcurrencyTest.setUpClass.__func__)
    dispose_test_database = classmethod(fixtures.LoanMySQLConcurrencyTest.dispose_test_database.__func__)
    setUp = fixtures.LoanMySQLConcurrencyTest.setUp
    user = fixtures.LoanMySQLConcurrencyTest.user
    pending = fixtures.LoanMySQLConcurrencyTest.pending

    def borrowed(self):
        loan, _ = self.pending('reminder')
        loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest())
        loan.borrowed_at = datetime.now() - timedelta(days=31)
        loan.due_at = datetime.now() - timedelta(days=1)
        self.db.commit()
        identifiers = loan.id, self.reader.id
        self.db.commit()
        return identifiers

    def test_two_workers_with_old_snapshots_emit_once(self):
        loan_id, _ = self.borrowed()
        barrier = Barrier(2)
        def run():
            with Session(self.engine) as db:
                db.get(Loan, loan_id)
                barrier.wait(timeout=10)
                return generate_reminders(db)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=20) for f in futures), [0, 1])
        self.assertEqual(self.db.query(Notification).filter_by(resource_id=loan_id, kind='loan_overdue').count(), 1)

    def test_committed_return_suppresses_worker_with_old_snapshot(self):
        loan_id, reader_id = self.borrowed()
        with Session(self.engine) as worker:
            worker.get(Loan, loan_id)
            with Session(self.engine) as db:
                loan_service.request_return(db, db.get(User, reader_id), loan_id)
            self.assertEqual(generate_reminders(worker), 0)

    def test_upgrade_on_mysql_preserves_existing_accounts_and_is_repeatable(self):
        # This fixture always creates a random disposable schema.
        self.assertTrue(self.test_database.startswith('library_loan_test_'))
        before = self.db.query(User.id, User.username, User.password, User.token_version).order_by(User.id).all()
        self.db.commit()
        Notification.__table__.drop(self.engine)
        statements = upgrade(self.engine)
        self.assertTrue(any('CREATE TABLE' in statement for statement in statements))
        upgrade(self.engine, apply=True)
        self.assertEqual(upgrade(self.engine, apply=True), [])
        self.assertEqual(before, self.db.query(User.id, User.username, User.password, User.token_version).order_by(User.id).all())
