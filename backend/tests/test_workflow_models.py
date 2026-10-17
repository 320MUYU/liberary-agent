import unittest
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models
from app.database import Base
from app.models.users import User
from app.models.workflow import WorkflowRun, WorkflowStep
from app.schemas.workflow import WorkflowPlan
from scripts.upgrade_agent_workflows import upgrade


class WorkflowModelsTest(unittest.TestCase):
    def test_plan_is_bounded_and_never_accepts_model_supplied_identity_or_conditions(self):
        step = {"task_type": "borrow", "query": "找书", "title": "查找图书", "read_only": True}
        self.assertEqual(len(WorkflowPlan(steps=[step]).steps), 1)
        for invalid in ({"steps": [step] * 4}, {"steps": []},
                {"steps": [{**step, "user_id": 99}]},
                {"steps": [{**step, "conditions": {"people": 1}}]},
                {"steps": [{**step, "task_type": "admin"}]},
                {"steps": [step], "clarification": "缺条件"}):
            with self.assertRaises(ValidationError):
                WorkflowPlan.model_validate(invalid)
        self.assertEqual(WorkflowPlan(steps=[], clarification="请说明需要查什么").steps, [])

    def test_upgrade_preview_is_read_only_and_repeat_preserves_existing_rows(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        User.__table__.create(engine)
        with Session(engine) as db:
            db.add(User(username="old", password="hash", name="旧用户", role="student"))
            db.commit()
        self.assertEqual(len(upgrade(engine)), 2)
        self.assertFalse(inspect(engine).has_table("agent_workflows"))
        self.assertEqual(len(upgrade(engine, apply=True)), 2)
        self.assertEqual(upgrade(engine, apply=True), [])
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT name FROM users")).scalar(), "旧用户")

    def test_parent_step_and_child_identity_cannot_be_duplicated(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(username="reader", password="hash", name="读者", role="student")
            db.add(user); db.flush()
            db.add(WorkflowRun(workflow_id="parent", user_id=user.id, query="找书", request={"query": "找书"}, expires_at=datetime.now() + timedelta(days=1)))
            db.commit()
            db.add(WorkflowStep(workflow_id="parent", position=0, child_run_id="child", spec={}))
            db.commit()
            db.add(WorkflowStep(workflow_id="parent", position=0, child_run_id="other", spec={}))
            with self.assertRaises(IntegrityError):
                db.commit()
