"""模型集中导出

SQLAlchemy 只认识"已经被 import 过"的模型类：没导入的模型不会注册到
Base.metadata，create_all 也就不会建它的表。所以在包的 __init__ 里统一导出，
让入口只要 `import app.models` 就能把全部表结构注册齐。

另外 Lab 和 Equipment 之间用字符串形式的 relationship（"Equipment" / "Lab"）
互相引用，这样两个模块不用互相 import，避免循环导入；代价是这两个类必须
都被导入过，SQLAlchemy 才解析得出关系——这也是要在这里统一导出的原因。
"""

from app.models.book_copies import BookCopy
from app.models.books import Book
from app.models.equipments import Equipment
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.models.users import User

__all__ = ["Book", "BookCopy", "Equipment", "Lab", "Reservation", "User"]
