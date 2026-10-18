from datetime import datetime, time, timedelta
import unittest
from unittest.mock import patch

from app.agent.policy import RunBudget
from app.models.reservations import Reservation
from app.schemas.reservation import ReservationReviewRequest
from app.services import reservation_service
from app.services.chat_tools import execute_chat_tool, tool_definitions
from app.services.time_context import BEIJING
from tests import test_reservation as fixtures


class ChatToolsTest(unittest.TestCase):
    setUp = fixtures.ReservationFlowTest.setUp
    tearDown = fixtures.ReservationFlowTest.tearDown
    request = fixtures.ReservationFlowTest.request

    def call(self, name, args, now=None, budget=None):
        return execute_chat_tool(self.db, self.student.id, name, args, budget or RunBudget(),
            now=now or datetime.combine(self.day - timedelta(days=1), time(10), tzinfo=BEIJING))

    def slot(self, **changes):
        return {"date_expression": self.day.isoformat(), "start": "14:00", "end": "16:00", **changes}

    def test_catalogue_needs_no_booking_form_and_never_claims_opening_or_availability(self):
        result = self.call("search_space_catalogue", {"keyword": "研讨"})
        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["spaces"][0]["id"], self.lab.id)
        self.assertNotIn("can_reserve", data["spaces"][0])
        self.assertEqual(data["opening_calendar"], "not_configured")
        self.assertEqual(self.db.query(Reservation).count(), 0)

    def test_slot_query_needs_no_purpose_and_optional_people_does_not_invent_capacity_requirement(self):
        self.lab.capacity = 1
        self.db.commit()
        result = self.call("check_space_availability", self.slot())
        self.assertTrue(result["data"]["spaces"][0]["can_reserve"])
        result = self.call("check_space_availability", self.slot(people=3))
        self.assertIn("capacity", result["data"]["spaces"][0]["unavailable_reasons"])
        self.assertEqual(self.db.query(Reservation).count(), 0)

    def test_pending_and_approved_results_follow_business_rules_without_exposing_readers(self):
        row = reservation_service.create_reservation(self.db, self.other, self.request())
        self.assertTrue(self.call("check_space_availability", self.slot())["data"]["spaces"][0]["can_reserve"])
        reservation_service.review_reservation(self.db, self.admin, row.id, ReservationReviewRequest(status="approved"))
        data = self.call("check_space_availability", self.slot())["data"]
        self.assertIn("approved_conflict", data["spaces"][0]["unavailable_reasons"])
        self.assertNotIn(self.other.username, str(data))
        self.assertNotIn("applicant_id", str(data))
        self.assertEqual(self.db.query(Reservation).count(), 1)

    def test_bare_weekday_requires_clarification_without_querying_spaces(self):
        with patch("app.services.chat_tools.discover_spaces") as search:
            result = self.call("check_space_availability", self.slot(date_expression="周六"),
                now=datetime(2026, 10, 18, tzinfo=BEIJING))
        self.assertEqual(result["data"]["status"], "needs_clarification")
        self.assertIsNone(result["data"]["date"])
        search.assert_not_called()

    def test_beijing_lead_time_is_independent_of_server_local_timezone(self):
        noon = datetime.combine(self.day, time(12), tzinfo=BEIJING)
        data = self.call("check_space_availability", self.slot(), now=noon)["data"]
        self.assertTrue(data["spaces"][0]["can_reserve"])
        self.assertTrue(data["checked_at"].endswith("+08:00"))
        data = self.call("check_space_availability", self.slot(), now=noon + timedelta(seconds=1))["data"]
        self.assertIn("too_late", data["spaces"][0]["unavailable_reasons"])

    def test_unknown_write_tools_invalid_arguments_and_user_overrides_are_rejected(self):
        for name, args in [
            ("submit_reservation_decision", {}),
            ("check_space_availability", self.slot(start="25:00")),
            ("check_space_availability", self.slot(end="13:00")),
            ("check_space_availability", self.slot(people=True)),
            ("search_space_catalogue", {"user_id": self.other.id}),
            ("resolve_date_expression", {"expression": "明天", "now": "2030-01-01"}),
        ]:
            with self.subTest(name=name, args=args):
                self.assertFalse(self.call(name, args)["ok"])
        self.assertEqual(self.db.query(Reservation).count(), 0)
        self.assertEqual({tool["name"] for tool in tool_definitions()},
            {"resolve_date_expression", "search_space_catalogue", "check_space_availability"})

    def test_disabled_user_budget_and_database_failure_return_safe_errors(self):
        self.assertEqual(self.call("search_space_catalogue", {}, budget=RunBudget(max_tools=0))["error_code"], "budget_exceeded")
        with patch("app.services.chat_tools.search_space_catalogue", side_effect=RuntimeError("secret database detail")):
            result = self.call("search_space_catalogue", {})
        self.assertEqual(result["error_code"], "unavailable")
        self.assertNotIn("secret", str(result))
        self.student.status = 0
        self.db.commit()
        self.assertEqual(self.call("search_space_catalogue", {})["error_code"], "unauthorized")

    def test_past_date_is_not_silently_shifted_into_the_future(self):
        result = self.call("check_space_availability", self.slot(date_expression="昨天"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "past_date")

    def test_complete_chat_clarifies_then_reads_real_database_without_booking(self):
        from langchain_core.messages import AIMessage
        from app.schemas.ai import ChatMessage, ChatRequest
        from app.services.ai_services import chat
        import json

        class ConversationModel:
            def model_copy(self, update):
                return self

            def bind_tools(self, definitions):
                return self

            def invoke(model, messages):
                if messages[-1].type == "tool":
                    data = json.loads(messages[-1].content)["data"]
                    return AIMessage(content=data["conditions"]["date"] + " " + data["spaces"][0]["name"])
                if messages[-1].content == "周六有自习室吗":
                    return AIMessage(content="", tool_calls=[{"id": "d", "name": "resolve_date_expression",
                        "args": {"expression": "周六"}}])
                return AIMessage(content="", tool_calls=[{"id": "s", "name": "check_space_availability",
                    "args": self.slot()}])

        history = [ChatMessage(role="user", content="周六有自习室吗")]
        first = chat(ChatRequest(messages=history), model=ConversationModel(), db=self.db, user_id=self.student.id)
        self.assertIn("候选日期", first.content)
        history.extend([ChatMessage(role="assistant", content=first.content),
            ChatMessage(role="user", content=f"{self.day.isoformat()}，14点到16点")])
        second = chat(ChatRequest(messages=history), model=ConversationModel(), db=self.db, user_id=self.student.id)
        self.assertIn(self.lab.name, second.content)
        self.assertIn(self.day.isoformat(), second.content)
        self.assertEqual(self.db.query(Reservation).count(), 0)
