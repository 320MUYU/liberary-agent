"""可选 MySQL 行锁验收；仅在随机创建的独立临时数据库中运行。

RUN_LIBRARY_MYSQL_TEST=1 使用本地配置的 MySQL 服务器认证；也可通过
MYSQL_LIBRARY_TEST_URL 指定测试服务器。URL 中的数据库名称不会使用。
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.common.exceptions import BusinessException
from app.config import settings
from app.database import Base
from app.models.book_copies import BookCopy
from app.models.books import Book
from app.models.loans import Loan
from app.models.users import User
from app.schemas.loan import BorrowConfirmRequest, LoanRequest
from app.services import book_service, loan_service


@unittest.skipUnless(
    os.environ.get("MYSQL_LIBRARY_TEST_URL") or os.environ.get("RUN_LIBRARY_MYSQL_TEST") == "1",
    "需显式启用独立 MySQL 临时库并发测试",
)
class LoanMySQLConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ.get("MYSQL_LIBRARY_TEST_URL") or settings.DATABASE_URL)
        if url.get_backend_name() != "mysql":
            raise unittest.SkipTest("并发验收需要 MySQL 行锁")
        # 无论传入 URL 指向哪个库，都强制新建随机库；只清理该随机库。
        cls.test_database = "library_loan_test_" + uuid4().hex
        cls.server = create_engine(url._replace(database=None), isolation_level="AUTOCOMMIT")
        with cls.server.connect() as connection:
            connection.execute(text(f"CREATE DATABASE `{cls.test_database}` CHARACTER SET utf8mb4"))
        cls.addClassCleanup(cls.dispose_test_database)
        cls.engine = create_engine(url.set(database=cls.test_database), pool_size=5)
        Base.metadata.create_all(cls.engine)

    @classmethod
    def dispose_test_database(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if not cls.test_database.startswith("library_loan_test_") or len(cls.test_database) != 50:
            raise RuntimeError("临时数据库名称校验失败，拒绝清理")
        try:
            with cls.server.connect() as connection:
                connection.execute(text(f"DROP DATABASE `{cls.test_database}`"))
        finally:
            cls.server.dispose()

    def setUp(self):
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.namespace = uuid4().hex[:12]
        self.admin = self.user("admin", "admin")
        self.reader = self.user("reader")
        self.other = self.user("other")
        self.db.commit()
        self.admin_id = self.admin.id

    def user(self, suffix, role="student"):
        user = User(
            username=f"{self.namespace}-{suffix}", password="hash", name=suffix, role=role
        )
        self.db.add(user)
        self.db.flush()
        return user

    def pending(self, suffix, reader=None, book=None):
        if book is None:
            book = Book(title=f"并发验收 {suffix}", author="验收作者")
            self.db.add(book)
            self.db.flush()
            self.db.add(BookCopy(
                book_id=book.id, barcode=f"{self.namespace}-{suffix}", location="验收书架"
            ))
            self.db.commit()
        loan = loan_service.create_loan(
            self.db, reader or self.reader, LoanRequest(book_id=book.id)
        )
        return loan, book

    def concurrent_confirm(
        self, loan_ids, synchronize_availability=False, synchronize_after_availability=False
    ):
        barrier = Barrier(len(loan_ids))
        availability_barrier = Barrier(len(loan_ids))
        original_available_copy = loan_service._available_copy

        def synchronized_available_copy(*args, **kwargs):
            # 两边均检查完借阅上限后再检查对方已借副本，稳定复现交叉锁。
            if not synchronize_after_availability:
                availability_barrier.wait(timeout=10)
            copy = original_available_copy(*args, **kwargs)
            if synchronize_after_availability:
                availability_barrier.wait(timeout=10)
            return copy

        def confirm(loan_id):
            with Session(self.engine) as db:
                db.execute(text("SET SESSION innodb_lock_wait_timeout = 5"))
                admin = db.get(User, self.admin_id)
                # 主动建立旧快照，确保服务使用锁定读重查状态和库存。
                db.query(Loan).filter(Loan.id == loan_id).one()
                barrier.wait(timeout=10)
                try:
                    loan_service.confirm_borrow(db, admin, loan_id, BorrowConfirmRequest())
                    return 200
                except BusinessException as exc:
                    return exc.code

        self.db.commit()
        synchronization = (
            patch.object(loan_service, "_available_copy", side_effect=synchronized_available_copy)
            if synchronize_availability or synchronize_after_availability else nullcontext()
        )
        with synchronization:
            with ThreadPoolExecutor(max_workers=len(loan_ids)) as executor:
                futures = [executor.submit(confirm, loan_id) for loan_id in loan_ids]
                return [future.result(timeout=20) for future in futures]

    def test_two_readers_compete_for_last_copy(self):
        first, book = self.pending("single")
        second, _ = self.pending("other", reader=self.other, book=book)
        ids = (first.id, second.id)
        self.assertEqual(sorted(self.concurrent_confirm(ids)), [200, 409])
        self.db.expire_all()
        self.assertEqual(
            self.db.query(Loan).filter(Loan.id.in_(ids), Loan.active_copy_id.is_not(None)).count(), 1
        )

    def test_mysql_inventory_contract_uses_integer_json_before_and_after_borrow(self):
        loan, book = self.pending("integer-stock")
        before = book_service.book_response(self.db, book).model_dump(mode="json")
        self.assertIs(type(before["available_copies"]), int)
        self.assertEqual(before["available_copies"], 1)
        loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest())
        after = book_service.book_response(self.db, book).model_dump(mode="json")
        self.assertIs(type(after["available_copies"]), int)
        self.assertEqual(after["available_copies"], 0)
        self.assertIs(type(after["total_copies"]), int)
        self.assertEqual(after["total_copies"], 1)

    def test_two_books_for_same_reader_do_not_exceed_five(self):
        for number in range(4):
            loan, _ = self.pending(f"existing-{number}")
            loan_service.confirm_borrow(self.db, self.admin, loan.id, BorrowConfirmRequest())
        first, _ = self.pending("fifth")
        second, _ = self.pending("sixth")
        self.assertEqual(sorted(self.concurrent_confirm((first.id, second.id))), [200, 409])
        self.db.expire_all()
        self.assertEqual(
            self.db.query(Loan).filter(
                Loan.reader_id == self.reader.id, Loan.status.in_(("borrowed", "return_pending"))
            ).count(), 5
        )

    def test_same_application_cannot_be_confirmed_twice(self):
        loan, _ = self.pending("duplicate")
        self.assertEqual(sorted(self.concurrent_confirm((loan.id, loan.id))), [200, 409])
        self.db.expire_all()
        saved = self.db.get(Loan, loan.id)
        self.assertEqual(saved.status, "borrowed")
        self.assertEqual(saved.active_copy_id, saved.copy_id)

    def test_cross_readers_with_existing_loans_can_borrow_other_books(self):
        existing_x, book_x = self.pending("cross-x-first", reader=self.other)
        existing_y, book_y = self.pending("cross-y-first", reader=self.reader)
        loan_service.confirm_borrow(self.db, self.admin, existing_x.id, BorrowConfirmRequest())
        loan_service.confirm_borrow(self.db, self.admin, existing_y.id, BorrowConfirmRequest())
        self.db.add_all([
            BookCopy(book_id=book_x.id, barcode=f"{self.namespace}-cross-x-second", location="书架"),
            BookCopy(book_id=book_y.id, barcode=f"{self.namespace}-cross-y-second", location="书架"),
        ])
        self.db.commit()
        pending_x, _ = self.pending("cross-x-pending", reader=self.reader, book=book_x)
        pending_y, _ = self.pending("cross-y-pending", reader=self.other, book=book_y)
        ids = (pending_x.id, pending_y.id)
        # 两边都应能完成占用记录的共享读取；独占读取的原始死锁会让此屏障失败。
        results = self.concurrent_confirm(ids, synchronize_after_availability=True)
        self.assertIn(200, results)
        self.assertTrue(all(result in (200, 409) for result in results))
        for loan_id, result in zip(ids, results):
            if result == 409:
                loan_service.confirm_borrow(self.db, self.admin, loan_id, BorrowConfirmRequest())
        self.db.expire_all()
        active = self.db.query(Loan).filter(
            Loan.reader_id.in_((self.reader.id, self.other.id)), Loan.active_copy_id.is_not(None)
        ).all()
        self.assertEqual(len(active), 4)
        self.assertEqual(len({loan.active_copy_id for loan in active}), 4)
        self.assertEqual(sum(loan.reader_id == self.reader.id for loan in active), 2)
        self.assertEqual(sum(loan.reader_id == self.other.id for loan in active), 2)

    def test_distinct_books_gap_conflict_is_safe_and_can_be_retried(self):
        first, _ = self.pending("gap-first", reader=self.reader)
        second, _ = self.pending("gap-second", reader=self.other)
        ids = (first.id, second.id)
        results = self.concurrent_confirm(ids, synchronize_after_availability=True)
        self.assertIn(200, results)
        self.assertTrue(all(result in (200, 409) for result in results))
        for loan_id, result in zip(ids, results):
            if result == 409:
                # 回滚必须释放锁和中间写入；失败方可立即重试成功。
                loan_service.confirm_borrow(self.db, self.admin, loan_id, BorrowConfirmRequest())
        self.db.expire_all()
        self.assertEqual(
            self.db.query(Loan).filter(Loan.id.in_(ids), Loan.status == "borrowed").count(), 2
        )


if __name__ == "__main__":
    unittest.main()
