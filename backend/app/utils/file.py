"""文件落盘工具

只做「校验 + 落盘 + 返回元信息」三件事，不碰 Response、不管路由。
放在 utils 而不是 services，是因为它不碰数据库、也不需要会话，
和 bcrypt.py / jwt.py 一样属于纯工具。
"""

import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.common.exceptions import BusinessException
from app.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, UPLOAD_DIR


def save_upload(file: UploadFile) -> dict:
    """校验并保存上传的文件，返回 {original_name, disk_name, size, url}"""
    if not file.filename:
        raise BusinessException(message="文件名不能为空")

    # 原始的文件名  用户头像.jpg
    # 再过一遍 basename：浏览器可能传来 "../../x.jpg" 这种带目录的名字，
    # 直接拿去拼路径会被跳出上传目录
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

    # 设置唯一的文件名称
    # 不用原始文件名落盘：同名文件会互相覆盖，而且用户传的名字里可能带
    # 中文、空格、特殊字符，时间戳 + 随机串既避免冲突也避开这些麻烦
    disk_name = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}{ext}"
    # 文件存储的实际路径
    save_path = UPLOAD_DIR / disk_name

    # 流式写文件：不把整个文件读进内存，大文件也不会把服务撑爆
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {
        "original_name": original_name,
        "disk_name": disk_name,
        "size": file.size,
        "url": f"/uploads/{disk_name}",
    }
