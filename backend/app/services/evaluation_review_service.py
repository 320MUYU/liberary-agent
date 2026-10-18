"""Import once, persist drafts, and count only explicit human submissions."""

import copy
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.common.exceptions import BusinessException
from app.models.evaluation_review import EvaluationRun, EvaluationCaseReview
from app.services.evaluation_reports import apply_reviews, summarize, validate_report


def _run(db, run_id):
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise BusinessException("审核报告不存在", 404)
    return run


def _reviews(db, run_id):
    return {row.case_id: row for row in db.scalars(select(EvaluationCaseReview).where(
        EvaluationCaseReview.run_id == run_id)).all()}


def _decision(row):
    return {"status": row.status, "answer_correct": row.answer_correct,
            "citations_support": row.citations_support, "notes": row.notes,
            "revision": row.revision, "reviewer_id": row.reviewer_id, "reviewer": row.reviewer,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "updated_at": row.update_time.isoformat() if row.revision else None}


def _rows(db, run):
    reviews = _reviews(db, run.id)
    rows = copy.deepcopy(run.payload["results"])
    for row in rows:
        row["review"] = _decision(reviews[row["id"]])
    return rows


def _summary(run, rows):
    return {"id": run.id, "name": run.name, "report_id": run.report_id,
            "synthetic": run.payload.get("synthetic"), "split": run.payload.get("split"),
            "imported_at": run.create_time.isoformat(), "metrics": summarize(rows),
            "drafts": sum(row["review"]["status"] == "draft" for row in rows)}


def import_report(db, report, name, admin):
    try:
        clean = validate_report(report)
    except ValueError as exc:
        raise BusinessException(str(exc)) from exc
    existing = db.scalar(select(EvaluationRun).where(EvaluationRun.report_id == clean["report_id"]))
    if existing:
        return get_run(db, existing.id)
    run = EvaluationRun(report_id=clean["report_id"], name=name, payload=clean, imported_by=admin.id)
    try:
        db.add(run)
        db.flush()
        db.add_all(EvaluationCaseReview(run_id=run.id, case_id=row["id"]) for row in clean["results"])
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(EvaluationRun).where(EvaluationRun.report_id == clean["report_id"]))
        if existing is None:
            raise
        return get_run(db, existing.id)
    return get_run(db, run.id)


def list_runs(db):
    return [_summary(run, _rows(db, run)) for run in db.scalars(
        select(EvaluationRun).order_by(EvaluationRun.id.desc())).all()]


def get_run(db, run_id, status="all"):
    run = _run(db, run_id)
    rows = _rows(db, run)
    result = _summary(run, rows)
    def include(row):
        review = row["review"]
        return (status == "all"
                or status == "pending" and review["status"] != "reviewed"
                or status == "reviewed" and review["status"] == "reviewed"
                or status == "human_negative" and review["status"] == "reviewed" and (
                    review["answer_correct"] is False or review["citations_support"] is False)
                or status == "automatic_failure" and not row["contract_pass"])
    result["cases"] = [{key: row.get(key) for key in (
        "id", "question", "category", "contract_pass", "error", "review")}
        for row in rows if include(row)]
    return result


def get_case(db, run_id, case_id):
    run = _run(db, run_id)
    row = next((row for row in run.payload["results"] if row["id"] == case_id), None)
    if row is None:
        raise BusinessException("审核题目不存在", 404)
    result = copy.deepcopy(row)
    result["review"] = _decision(_reviews(db, run_id)[case_id])
    return result


def save_review(db, run_id, case_id, decision, admin):
    case = get_case(db, run_id, case_id)
    if case.get("error") and decision.answer_correct is True:
        raise BusinessException("服务错误不能审核为正确回答")
    now = datetime.now()
    result = db.execute(update(EvaluationCaseReview).where(
        EvaluationCaseReview.run_id == run_id, EvaluationCaseReview.case_id == case_id,
        EvaluationCaseReview.revision == decision.revision,
    ).values(status=decision.status, answer_correct=decision.answer_correct,
             citations_support=decision.citations_support, notes=decision.notes,
             revision=decision.revision + 1, reviewer_id=admin.id,
             reviewer=f"{admin.name} ({admin.username})", update_time=now,
             reviewed_at=now if decision.status == "reviewed" else None),
        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise BusinessException("该题已被其他页面修改，请重新载入最新判断后再保存", 409)
    db.commit()
    db.expire_all()
    return get_case(db, run_id, case_id)


def export_reviews(db, run_id):
    run = _run(db, run_id)
    return {"report_id": run.report_id, "cases": [
        {"id": row.case_id, **{key: getattr(row, key) for key in (
            "reviewer", "answer_correct", "citations_support", "notes")}}
        for row in _reviews(db, run_id).values() if row.status == "reviewed"]}


def export_report(db, run_id):
    return apply_reviews(copy.deepcopy(_run(db, run_id).payload), export_reviews(db, run_id))

