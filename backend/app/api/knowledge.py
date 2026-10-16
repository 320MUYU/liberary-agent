from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin, get_current_user
from app.models.users import User
from app.schemas.knowledge import (
    DocumentResponse, TitleRequest, VersionResponse, SearchRequest, SearchResponse, IndexStatusResponse,
)
from app.services import knowledge_service, knowledge_diagnostics


router = APIRouter(tags=["知识库接口"])


@router.post("/admin/knowledge/search")
def search_knowledge(data: SearchRequest, _: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=SearchResponse.model_validate(knowledge_diagnostics.search(db, data)))


@router.get("/admin/knowledge/versions/{version_id}/index-status")
def index_status(version_id: int = Path(ge=1), _: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=IndexStatusResponse.model_validate(knowledge_diagnostics.index_status(db, version_id)))


def _validate_title(title: str, *, allow_blank: bool = False) -> str:
    if allow_blank and not title.strip():
        return ""
    try:
        return TitleRequest(title=title).title
    except ValidationError as exc:
        raise RequestValidationError(
            [dict(error, loc=("body", *error["loc"])) for error in exc.errors()]
        ) from exc


class SourceResponse(BaseModel):
    chunk_id: int = Field(gt=0)
    document_id: int
    version: int
    title: str
    page: int | None = None
    section: str | None = None
    text: str


@router.get("/admin/knowledge/documents")
def list_documents(
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    documents = knowledge_service.list_documents(db)
    return Response.success(
        data=[DocumentResponse.model_validate(document) for document in documents]
    )


@router.post("/admin/knowledge/documents")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    document = await knowledge_service.upload_document(
        db, file=file, title=_validate_title(title), user_id=admin.id
    )
    return Response.success(
        message="文档已上传，等待索引", data=DocumentResponse.model_validate(document)
    )


@router.post("/admin/knowledge/documents/{document_id}/versions")
async def upload_version(
    document_id: int = Path(ge=1),
    file: UploadFile = File(...),
    title: str = Form(""),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    document = await knowledge_service.upload_document(
        db,
        file=file,
        title=_validate_title(title, allow_blank=True),
        user_id=admin.id,
        document_id=document_id,
    )
    return Response.success(
        message="新版本已上传，等待索引", data=DocumentResponse.model_validate(document)
    )


@router.post("/admin/knowledge/documents/{document_id}/publish")
def publish_document(
    document_id: int = Path(ge=1),
    version_id: int | None = Query(None, ge=1),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    document = knowledge_service.publish_document(db, document_id, version_id)
    return Response.success(
        message="文档已发布", data=DocumentResponse.model_validate(document)
    )


@router.post("/admin/knowledge/documents/{document_id}/disable")
def disable_document(
    document_id: int = Path(ge=1),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    document = knowledge_service.disable_document(db, document_id)
    return Response.success(
        message="文档已停用", data=DocumentResponse.model_validate(document)
    )


@router.post("/admin/knowledge/versions/{version_id}/retry")
def retry_version(
    version_id: int = Path(ge=1),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    version = knowledge_service.retry_version(db, version_id)
    return Response.success(
        message="索引任务已重新排队", data=VersionResponse.model_validate(version)
    )


@router.delete("/admin/knowledge/documents/{document_id}")
def delete_document(
    document_id: int = Path(ge=1),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    knowledge_service.delete_document(db, document_id)
    return Response.success(message="文档已删除")


@router.get("/knowledge/sources/{chunk_id}")
def get_source(
    chunk_id: int = Path(ge=1),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = knowledge_service.get_source(db, chunk_id)
    return Response.success(data=SourceResponse.model_validate(source))
