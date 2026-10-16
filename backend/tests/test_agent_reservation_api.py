from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from langchain_core.messages import AIMessage

from tests import test_library_flow as fixtures
from app.agent.reservation_actions import decide_reservation


class AgentReservationApiTest(unittest.TestCase):
    setUp = fixtures.LibraryFlowTest.setUp
    request = fixtures.LibraryFlowTest.request

    def setup_space(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for key, value in [("AGENT_CHECKPOINT_PATH", Path(directory.name)/"space.sqlite"), ("AGENT_TOOL_TRANSPORT", "local")]:
            config = patch("app.agent.runtime.settings."+key, value)
            config.start(); self.addCleanup(config.stop)
        self.model_calls = 0
        def model(*args):
            self.model_calls += 1
            return AIMessage(content="已提交预约", tool_calls=([{"id":"s", "name":"search_spaces", "args":{}}] if self.model_calls % 2 else []))
        config = patch("app.agent.runtime.call_model", side_effect=model)
        config.start(); self.addCleanup(config.stop)
        self.space = self.request("POST", "/admin/lab", json={"name":"研讨室", "code":"SPACE-1", "building":"A", "floor":"1", "capacity":5, "category":"研讨室"})
        self.conditions = {"date":str(date.today()+timedelta(days=2)), "start":"14:00", "end":"16:00", "people":3, "purpose":"课程讨论"}

    def start(self, **changes):
        return self.request("POST", "/agent/runs", role="reader", json={
            "request_id":str(uuid4()), "query":"找研讨室", "task_type":"reservation", "conditions":self.conditions, **changes})

    def test_select_confirm_restore_replay_and_admin_status(self):
        self.setup_space()
        run = self.start()
        self.assertEqual(run["status"], "select_space")
        self.assertEqual(run["conditions"]["date"], self.conditions["date"])
        path = "/agent/runs/"+run["run_id"]
        preview = self.request("POST", path+"/select-space", role="reader", json={"space_id":self.space["id"]})
        self.assertEqual(preview["status"], "confirm_reservation")
        self.assertEqual(self.request("GET", "/reservation/mine", role="reader"), [])
        self.assertEqual(self.request("GET", path, role="reader")["action"], preview["action"])
        decision = {"action_id":preview["action"]["id"], "confirmed":True}
        receipt = self.request("POST", path+"/decision", role="reader", json=decision)
        self.assertEqual(receipt["status"], "reservation_pending")
        self.assertEqual(self.request("POST", path+"/decision", role="reader", json=decision)["receipt"], receipt["receipt"])
        self.request("PUT", f"/admin/reservation/{receipt['receipt']['reservation_id']}/review", json={"status":"approved"})
        self.assertEqual(self.request("GET", path, role="reader")["status"], "reservation_approved")

    def test_missing_conditions_binding_foreign_selection_and_tool_condition_override(self):
        self.setup_space()
        invalid = self.client.post("/api/agent/runs", headers=self.headers["reader"], json={"request_id":str(uuid4()),"query":"明天下午", "task_type":"reservation"})
        self.assertEqual(invalid.status_code, 422)
        with patch("app.agent.runtime.call_model", return_value=AIMessage(content="", tool_calls=[{
            "id":"s", "name":"search_spaces", "args":{"conditions":{**self.conditions,"people":1}}}])):
            run = self.start()
        self.assertEqual(run["status"], "tool_unavailable")
        run = self.start()
        path = "/agent/runs/"+run["run_id"]
        for role, space in [("other",self.space["id"]), ("reader",999)]:
            result = self.client.post("/api"+path+"/select-space", headers=self.headers[role],json={"space_id":space})
            self.assertIn(result.json()["code"], (404,409))
        result = self.client.post("/api/agent/runs", headers=self.headers["reader"], json={"request_id":run["run_id"],"query":"找研讨室","task_type":"reservation", "conditions":{**self.conditions,"people":4}})
        self.assertEqual(result.json()["code"],409)

    def test_cancel_and_committed_response_loss_recovery(self):
        self.setup_space()
        run = self.start(); path = "/agent/runs/"+run["run_id"]
        preview = self.request("POST", path+"/select-space", role="reader",json={"space_id":self.space["id"]})
        self.assertEqual(self.request("POST", path+"/decision",role="reader",json={"action_id":preview["action"]["id"],"confirmed":False})["status"],"cancelled")
        run = self.start(); path = "/agent/runs/"+run["run_id"]
        preview = self.request("POST", path+"/select-space",role="reader",json={"space_id":self.space["id"]})
        def interrupted(*args):
            decide_reservation(*args)
            raise RuntimeError("lost response")
        with patch("app.agent.runtime.decide_reservation",side_effect=interrupted):
            failed = self.client.post("/api"+path+"/decision",headers=self.headers["reader"],json={"action_id":preview["action"]["id"],"confirmed":True})
        self.assertEqual(failed.json()["code"],503)
        self.assertEqual(self.request("POST",path+"/retry",role="reader")["status"],"reservation_pending")
        self.assertEqual(len(self.request("GET","/reservation/mine",role="reader")),1)

    def test_page_refresh_rechecks_availability_and_keeps_conditions(self):
        self.setup_space()
        run = self.start(); path="/agent/runs/"+run["run_id"]
        data = {**self.space,"status":"maintenance"}
        allowed = {key:data[key] for key in ("name","code","building","floor","capacity","category","status")}
        self.request("PUT",f"/admin/lab/{self.space['id']}",json=allowed)
        refreshed=self.request("GET",path,role="reader")
        self.assertFalse(refreshed["spaces"][0]["can_reserve"])
        self.assertEqual(refreshed["conditions"]["people"],3)
        rejected=self.client.post("/api"+path+"/select-space",headers=self.headers["reader"],json={"space_id":self.space["id"]})
        self.assertEqual(rejected.json()["code"],409)

    def test_pagination_restores_current_page_and_does_not_call_model(self):
        self.setup_space()
        for index in range(6):
            self.request("POST","/admin/lab",json={"name":"研讨室", "code":f"SPACE-{index+2}",
                "building":"A", "floor":"1", "capacity":5, "category":"研讨室"})
        run=self.start(); path="/agent/runs/"+run["run_id"]
        calls=self.model_calls
        page=self.request("POST",path+"/spaces-page",role="reader",json={"page":2})
        self.assertEqual(page["page"],2)
        self.assertEqual(len(page["spaces"]),1)
        self.assertEqual(self.model_calls,calls)
        self.assertEqual(self.request("GET",path,role="reader")["spaces"],page["spaces"])
        selected=self.request("POST",path+"/select-space",role="reader",json={"space_id":page["spaces"][0]["id"]})
        self.assertEqual(selected["status"],"confirm_reservation")
