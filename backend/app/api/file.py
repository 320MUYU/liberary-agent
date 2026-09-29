from fastapi import APIRouter, File, UploadFile
from pathlib import Path
import os
from app.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from app.common.exceptions import BusinessException

router = APIRouter(prefix="/file",tags=["文件管理"])


@router.post("/upload")
def upload(file: UploadFile = File(...)):
    """文件上传的接口"""
    if not file.filename:
        raise BusinessException(message="文件名不能为空")

    # 原始的文件名  用户头像.jpg
    original_name = os.path.basename(file.filename)
    # 文件后缀 .jpg
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise BusinessException(message=f"不支持的文件后缀: {ext}")
    # 文件大小校验
    if file.size and file.size > MAX_FILE_SIZE:
        raise BusinessException(
            message=f"文件不能超过 {MAX_FILE_SIZE // 1024 // 1024}MB"
        )
