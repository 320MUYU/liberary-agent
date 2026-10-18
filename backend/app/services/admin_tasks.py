"""Small aggregate counts for administrator navigation; never load report payloads."""

from sqlalchemy import func, select

from app.models.evaluation_review import EvaluationCaseReview
from app.models.loans import Loan
from app.models.reservations import Reservation


def task_summary(db):
    def count(model, condition):
        return select(func.count()).select_from(model).where(condition).scalar_subquery()
    statement = select(
        count(Reservation, Reservation.status == "pending").label("reservation_pending"),
        count(Loan, Loan.status == "pending").label("borrow_pending"),
        count(Loan, Loan.status == "return_pending").label("return_pending"),
        count(EvaluationCaseReview, EvaluationCaseReview.status.in_(("pending_human", "draft"))).label("evaluation_pending"),
    )
    result = dict(db.execute(statement).mappings().one())
    result["total"] = sum(result.values())
    return result
