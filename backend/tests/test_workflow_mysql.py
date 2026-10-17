from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.agent import workflow
from app.common.exceptions import BusinessException
from app.models.agent import AgentRun
from app.models.workflow import WorkflowRun, WorkflowStep
from app.schemas.workflow import WorkflowPlan
from tests import test_loan_mysql as fixtures


@unittest.skipUnless(os.environ.get("MYSQL_LIBRARY_TEST_URL") or os.environ.get("RUN_LIBRARY_MYSQL_TEST") == "1", "需启用独立MySQL工作流并发测试")
class WorkflowMySQLTest(unittest.TestCase):
    setUpClass = classmethod(fixtures.LoanMySQLConcurrencyTest.setUpClass.__func__)
    dispose_test_database = classmethod(fixtures.LoanMySQLConcurrencyTest.dispose_test_database.__func__)
    setUp = fixtures.LoanMySQLConcurrencyTest.setUp
    user = fixtures.LoanMySQLConcurrencyTest.user

    def test_competing_advances_share_one_child_and_do_not_repeat_planning(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("app.agent.runtime.settings.AGENT_CHECKPOINT_PATH", Path(folder) / "graph.sqlite"), \
                patch("app.agent.runtime.settings.AGENT_TOOL_TRANSPORT", "local"), \
                patch("app.agent.workflow.plan_workflow", return_value=WorkflowPlan(steps=[{
                    "task_type": "my_loans", "title": "我的借阅", "query": "查询", "read_only": True}])), \
                patch("app.agent.runtime.call_model", return_value=AIMessage(content="")) as model:
            user_id = self.reader.id
            run = workflow.create_workflow(self.db, user_id, str(uuid4()), "查询我的借阅")
            workflow_id = run["workflow_id"]
            barrier = Barrier(2)
            def advance():
                with Session(self.engine) as db:
                    db.query(WorkflowRun).count()  # Establish an older MySQL snapshot.
                    barrier.wait(timeout=10)
                    try:
                        return workflow.operate(db, user_id, workflow_id, "retry")["status"]
                    except BusinessException as exc:
                        return exc.code
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: advance(), range(2)))
            self.assertTrue(all(result in {409, "completed"} for result in results), results)
            restored = workflow.operate(self.db, user_id, workflow_id)
            self.assertEqual(restored["status"], "completed")
            self.assertEqual(self.db.query(WorkflowStep).filter_by(workflow_id=workflow_id).count(), 1)
            self.assertEqual(self.db.query(AgentRun).filter_by(run_id=restored["steps"][0]["child_run_id"]).count(), 1)
            self.assertEqual(model.call_count, 2)
