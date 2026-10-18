"""Password changes revoke all older sessions without affecting other accounts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier
import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models
from app.common.exceptions import BusinessException
from app.config import settings
from app.database import Base, get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.models.users import User
from app.schemas.user import PasswordUpdateRequest
from app.services import auth_service, user_service
from app.utils.bcrypt import hash_password, verify_password
from app.utils.jwt import create_access_token, decode_access_token
from tests import test_loan_mysql as fixtures


class AuthTokenVersionTest(unittest.TestCase):
    password = "Original123"

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            password = hash_password(self.password)
            for user_id, username, role in ((1, "reader", "student"), (2, "admin", "admin"), (3, "other", "student")):
                db.add(User(id=user_id, username=username, password=password, name=username, role=role))
            db.commit()

        def session():
            with Session(self.engine) as db:
                yield db

        overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = session
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(overrides)))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def login(self, username="reader", password=None):
        response = self.client.post("/api/auth/login", json={"username": username, "password": password or self.password})
        self.assertEqual(response.json()["code"], 200, response.text)
        self.assertNotIn("token_version", response.json()["data"]["user"])
        return response.json()["data"]["token"]

    def headers(self, token):
        return {"Authorization": "Bearer " + token}

    def profile(self, token):
        return self.client.get("/api/user/info", headers=self.headers(token))

    def change(self, token, old=None, new="Changed123"):
        return self.client.put("/api/user/password", headers=self.headers(token), json={
            "old_password": old or self.password, "new_password": new, "confirm_password": new})

    def reset(self, admin, new="Reset123"):
        return self.client.put("/api/admin/user/1/password", headers=self.headers(admin), json={"new_password": new})

    def test_password_change_revokes_all_old_sessions_and_new_login_works(self):
        first, second, other = self.login(), self.login(), self.login("other")
        self.assertEqual(self.change(first).json()["code"], 200)
        for token in (first, second):
            response = self.profile(token)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], 401)
        self.assertEqual(self.profile(other).status_code, 200)
        old_login = self.client.post("/api/auth/login", json={"username": "reader", "password": self.password})
        self.assertEqual(old_login.json()["code"], 401)
        current = self.login(password="Changed123")
        self.assertEqual(decode_access_token(current)["token_version"], 1)
        self.assertEqual(self.profile(current).status_code, 200)

    def test_admin_reset_revokes_reader_sessions_and_preserves_admin_session(self):
        reader, another_session, admin = self.login(), self.login(), self.login("admin")
        self.assertEqual(self.reset(admin).json()["code"], 200)
        for token in (reader, another_session):
            self.assertEqual(self.profile(token).status_code, 401)
        self.assertEqual(self.profile(admin).status_code, 200)
        self.assertEqual(self.profile(self.login(password="Reset123")).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "reader", "password": self.password}).json()["code"], 401)

    def test_failed_change_validation_and_forbidden_reset_do_not_revoke_session(self):
        reader = self.login()
        self.assertEqual(self.change(reader, old="Wrong123").json()["code"], 400)
        self.assertEqual(self.change(reader, new="tiny").status_code, 422)
        self.assertEqual(self.reset(reader).status_code, 403)
        self.assertEqual(self.profile(reader).status_code, 200)
        with Session(self.engine) as db:
            self.assertEqual(db.get(User, 1).token_version, 0)
            self.assertTrue(verify_password(self.password, db.get(User, 1).password))

    def test_legacy_token_only_works_until_first_password_change(self):
        legacy = jwt.encode({"user_id": 1, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        self.assertEqual(self.profile(legacy).status_code, 200)
        self.assertEqual(self.change(legacy).json()["code"], 200)
        self.assertEqual(self.profile(legacy).status_code, 401)

    def test_invalid_or_mismatched_version_is_rejected_as_unauthenticated(self):
        for version in (None, -1, True, "0", 0.0, [], {}, 1):
            with self.subTest(version=version):
                token = jwt.encode({"user_id": 1, "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                    "token_version": version}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
                self.assertEqual(self.profile(token).status_code, 401)

    def test_repeated_changes_within_same_second_revoke_each_previous_version(self):
        with patch("app.utils.jwt.datetime") as clock:
            clock.now.return_value = datetime(2030, 1, 1, tzinfo=timezone.utc)
            initial = self.login()
            self.assertEqual(decode_access_token(initial)["token_version"], 0)
            self.assertEqual(self.change(initial).json()["code"], 200)
            middle = self.login(password="Changed123")
            self.assertEqual(self.change(middle, old="Changed123", new="ChangedAgain123").json()["code"], 200)
            current = self.login(password="ChangedAgain123")
        self.assertEqual(decode_access_token(current)["token_version"], 2)
        for token in (initial, middle):
            self.assertEqual(self.profile(token).status_code, 401)
        self.assertEqual(self.profile(current).status_code, 200)

    def test_password_and_version_are_rolled_back_together_on_commit_failure(self):
        token = self.login()
        for operation in ("change", "reset"):
            with self.subTest(operation=operation), Session(self.engine) as db:
                user = db.get(User, 1)
                def fail_commit():
                    db.flush()
                    raise RuntimeError("simulated database failure")

                with patch.object(db, "commit", side_effect=fail_commit):
                    with self.assertRaisesRegex(RuntimeError, "simulated database failure"):
                        if operation == "change":
                            user_service.update_password(db, user, PasswordUpdateRequest(
                                old_password=self.password, new_password="Changed123", confirm_password="Changed123"))
                        else:
                            user_service.reset_user_password(db, 1, "Reset123")
                db.expire_all()
                self.assertEqual(db.get(User, 1).token_version, 0)
                self.assertTrue(verify_password(self.password, db.get(User, 1).password))
        self.assertEqual(self.profile(token).status_code, 200)

    def test_authentication_refreshes_a_previously_loaded_user(self):
        token = self.login()
        with Session(self.engine) as db:
            original = db.get(User, 1)
            self.assertEqual(original.token_version, 0)
            with Session(self.engine) as writer:
                user_service.reset_user_password(writer, 1, "Reset123")
            with self.assertRaises(HTTPException) as failure:
                get_current_user(token=token, db=db)
            self.assertEqual(failure.exception.status_code, 401)


@unittest.skipUnless(os.environ.get("MYSQL_LIBRARY_TEST_URL") or os.environ.get("RUN_LIBRARY_MYSQL_TEST") == "1",
    "需显式启用独立 MySQL 临时库并发鉴权测试")
class AuthTokenVersionMySQLTest(unittest.TestCase):
    setUpClass = classmethod(fixtures.LoanMySQLConcurrencyTest.setUpClass.__func__)
    dispose_test_database = classmethod(fixtures.LoanMySQLConcurrencyTest.dispose_test_database.__func__)
    setUp = fixtures.LoanMySQLConcurrencyTest.setUp
    user = fixtures.LoanMySQLConcurrencyTest.user

    def test_parallel_admin_resets_do_not_lose_version_increments(self):
        reader_id = self.reader.id
        barrier = Barrier(2)

        def reset(password):
            with Session(self.engine) as db:
                cached = db.get(User, reader_id)
                self.assertEqual(cached.token_version, 0)
                barrier.wait(timeout=10)
                user_service.reset_user_password(db, reader_id, password)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reset, password) for password in ("FirstReset123", "SecondReset123")]
            for future in futures:
                future.result(timeout=20)
        with Session(self.engine) as db:
            self.assertEqual(db.get(User, reader_id).token_version, 2)
            for version in (0, 1):
                with self.assertRaises(HTTPException):
                    get_current_user(token=create_access_token(reader_id, version), db=db)

    def test_parallel_changes_cannot_reuse_a_revoked_authentication_snapshot(self):
        reader_id = self.reader.id
        self.reader.password = hash_password("Original123")
        self.db.commit()
        barrier = Barrier(2)

        def change(password):
            with Session(self.engine) as db:
                user = get_current_user(token=create_access_token(reader_id), db=db)
                barrier.wait(timeout=10)
                try:
                    user_service.update_password(db, user, PasswordUpdateRequest(
                        old_password="Original123", new_password=password, confirm_password=password))
                    return 200
                except BusinessException as exc:
                    return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(change, password) for password in ("FirstChange123", "SecondChange123")]
            statuses = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(statuses), [200, 401])
        with Session(self.engine) as db:
            user = db.get(User, reader_id)
            self.assertEqual(user.token_version, 1)
            password = "FirstChange123" if verify_password("FirstChange123", user.password) else "SecondChange123"
            _, token = auth_service.login(db, user.username, password)
            self.assertEqual(get_current_user(token=token, db=db).id, reader_id)
