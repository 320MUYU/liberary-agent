"""Business events commit atomically; reminders recover without duplicates."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models
from app.database import Base
from app.models.users import User
from app.models.books import Book
from app.models.book_copies import BookCopy
from app.models.loans import Loan
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.models.notification import Notification
from app.schemas.loan import BorrowConfirmRequest, LoanRejectRequest
from app.schemas.reservation import ReservationReviewRequest
from app.services import loan_service, reservation_service
from app.services.notification_reminders import generate_reminders


class NotificationEventsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.admin = User(username='admin', password='hash', name='管理员', role='admin')
        self.reader = User(username='reader', password='hash', name='读者', role='student')
        self.book = Book(title='测试图书', author='作者')
        self.lab = Lab(name='阅览室', code='A101', building='A', floor='1', capacity=10, category='study')
        self.db.add_all([self.admin, self.reader, self.book, self.lab])
        self.db.flush()
        self.db.add(BookCopy(book_id=self.book.id, barcode='N001', location='书架'))
        self.db.commit()
        self.now = datetime(2026, 10, 19, 12)

    def loan(self, status='pending', due=None):
        book = Book(title='测试图书', author='作者')
        self.db.add(book)
        self.db.flush()
        copy = BookCopy(book_id=book.id, barcode=f'N{book.id:03}', location='书架')
        self.db.add(copy)
        self.db.flush()
        active = status in ('borrowed', 'return_pending')
        occupied = active or status == 'returned'
        due = (due or self.now) if occupied else None
        row = Loan(reader_id=self.reader.id, book_id=book.id, status=status, due_at=due,
            open_book_id=book.id if active or status == 'pending' else None,
            copy_id=copy.id if occupied else None, active_copy_id=copy.id if active else None,
            borrowed_at=due - timedelta(days=30) if occupied else None,
            return_requested_at=due if status in ('return_pending', 'returned') else None,
            returned_at=due if status == 'returned' else None)
        self.db.add(row)
        self.db.commit()
        return row

    def reservation(self):
        row = Reservation(applicant_id=self.reader.id, lab_id=self.lab.id,
            date=(datetime.now() + timedelta(days=5)).date(), start='10:00', end='11:00',
            people=1, purpose='阅读')
        self.db.add(row)
        self.db.commit()
        return row

    def test_borrow_reject_and_return_notify_the_owner(self):
        row = self.loan()
        loan_service.confirm_borrow(self.db, self.admin, row.id, BorrowConfirmRequest())
        loan_service.request_return(self.db, self.reader, row.id)
        loan_service.confirm_return(self.db, self.admin, row.id)
        rejected = self.loan()
        loan_service.reject_loan(self.db, self.admin, rejected.id, LoanRejectRequest(reason='资料不全'))
        notices = self.db.query(Notification).order_by(Notification.id).all()
        self.assertEqual([n.kind for n in notices], ['loan_borrowed', 'loan_returned', 'loan_rejected'])
        self.assertTrue(all(n.user_id == self.reader.id and '测试图书' in n.content for n in notices))
        self.assertIn('资料不全', notices[-1].content)

    def test_reservation_approved_and_rejected_include_review_note(self):
        for status in ('approved', 'rejected'):
            row = self.reservation()
            reservation_service.review_reservation(self.db, self.admin, row.id,
                ReservationReviewRequest(status=status, review_note='审核说明'))
            notice = self.db.query(Notification).filter_by(resource_id=row.id).one()
            self.assertEqual(notice.kind, 'reservation_' + status)
            self.assertEqual(notice.user_id, self.reader.id)
            self.assertIn('阅览室', notice.content)
            self.assertIn('审核说明', notice.content)

    def test_notification_failure_rolls_back_borrow_and_review(self):
        loan, reservation = self.loan(), self.reservation()
        for module, action, model, target in (
            (loan_service, lambda: loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest()), Loan, loan.id),
            (reservation_service, lambda: reservation_service.review_reservation(self.db, self.admin, reservation.id,
                ReservationReviewRequest(status='approved')), Reservation, reservation.id)):
            with self.subTest(module=module.__name__):
                with patch.object(module, 'emit_notification', side_effect=RuntimeError('inbox unavailable')):
                    with self.assertRaisesRegex(RuntimeError, 'inbox unavailable'):
                        action()
                with Session(self.engine) as db:
                    self.assertEqual(db.get(model, target).status, 'pending')
                    self.assertEqual(db.query(Notification).count(), 0)

    def test_reminder_boundaries_restart_and_current_phase_only(self):
        outside = self.loan('borrowed', self.now + timedelta(days=3, seconds=1))
        soon = self.loan('borrowed', self.now + timedelta(days=3))
        exact = self.loan('borrowed', self.now)
        overdue = self.loan('borrowed', self.now - timedelta(seconds=1))
        self.assertEqual(generate_reminders(self.db, now=self.now, batch_size=2), 3)
        self.assertEqual(generate_reminders(self.db, now=self.now), 0)
        actual = {(n.resource_id, n.kind) for n in self.db.query(Notification).all()}
        self.assertEqual(actual, {(soon.id, 'loan_due_soon'), (exact.id, 'loan_due_soon'), (overdue.id, 'loan_overdue')})
        self.assertNotIn(outside.id, {n.resource_id for n in self.db.query(Notification).all()})
        self.assertEqual(generate_reminders(self.db, now=self.now + timedelta(days=4)), 3)

    def test_reminders_skip_inactive_and_non_borrowed_loans(self):
        for status in ('pending', 'return_pending', 'returned', 'cancelled', 'rejected'):
            self.loan(status, self.now - timedelta(days=1))
        self.loan('borrowed', self.now)
        self.reader.status = 0
        self.db.commit()
        self.assertEqual(generate_reminders(self.db, now=self.now), 0)

    def test_failed_reminder_rolls_back_and_next_scan_retries(self):
        self.loan('borrowed', self.now)
        with patch('app.services.notification_reminders.emit_notification', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                generate_reminders(self.db, now=self.now)
        self.assertEqual(self.db.query(Notification).count(), 0)
        self.assertEqual(generate_reminders(self.db, now=self.now), 1)
