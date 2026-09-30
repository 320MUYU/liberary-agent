from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    """文件上传返回体

    - original_name 是用户的原始文件名，只作展示回显，不参与存储
    - disk_name 是真正落盘的文件名（时间戳 + 随机串 + 后缀），全局唯一
    - url 是可直接访问的静态路径，头像字段存的就是它
    - size 直接用 UploadFile 给的字节数；流式上传时 FastAPI 有可能拿不到，所以可空
    """

    original_name: str
    disk_name: str
    size: int | None = None
    url: str
