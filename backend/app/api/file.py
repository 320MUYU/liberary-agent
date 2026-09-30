from fastapi import APIRouter, File, UploadFile

from app.common.response import Response
from app.schemas.file import FileUploadResponse
from app.utils.file import save_upload

router = APIRouter(prefix="/file", tags=["文件管理"])


@router.post("/upload")
def upload(file: UploadFile = File(...)):
    """文件上传的接口

    后缀白名单、大小上限、落盘命名这些规则见 utils/file.py。
    """
    data = save_upload(file)

    return Response.success(data=FileUploadResponse(**data))
