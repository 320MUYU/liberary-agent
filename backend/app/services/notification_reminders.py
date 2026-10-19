"""Bounded scans with current locking reads, shared with normal loan operations."""

from datetime import datetime, timedelta

from app.models.books import Book
from app.models.loans import Loan
from app.models.users import User
from app.services.notification_service import emit_notification


def generate_reminders(db, *, now=None, batch_size=100):
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    now = now or datetime.now()
    horizon = now + timedelta(days=3)
    last_id, created = 0, 0
    while True:
        candidates = db.query(Loan.id, Loan.reader_id).filter(Loan.id > last_id,
            Loan.status == "borrowed", Loan.due_at <= horizon).order_by(Loan.id).limit(batch_size).all()
        # Discard the scan snapshot before rechecking mutable state under locks.
        db.commit()
        if not candidates:
            return created
        for loan_id, reader_id in candidates:
            last_id = loan_id
            try:
                # Same first lock as borrow/return. Never acquire Book after Loan.
                reader = db.query(User).filter_by(id=reader_id).populate_existing().with_for_update().first()
                loan = db.query(Loan).filter_by(id=loan_id).populate_existing().with_for_update().first()
                if (reader is not None and reader.status == 1 and loan is not None
                        and loan.status == "borrowed" and loan.due_at and loan.due_at <= horizon):
                    phase = "overdue" if loan.due_at < now else "due_soon"
                    key = f"loan:{loan.id}:{phase}"
                    from app.models.notification import Notification
                    exists = db.query(Notification.id).filter_by(user_id=reader_id, event_key=key).with_for_update().first()
                    if exists is None:
                        book = db.get(Book, loan.book_id)
                        title = "图书已逾期" if phase == "overdue" else "图书即将到期"
                        emit_notification(db, user_id=reader_id, event_key=key, kind=f"loan_{phase}",
                            title=title, resource_type="loan", resource_id=loan.id,
                            content=f"《{book.title}》应于 {loan.due_at:%Y-%m-%d %H:%M} 前归还。请及时办理归还。")
                        created += 1
                db.commit()
            except Exception:
                db.rollback()
                raise
