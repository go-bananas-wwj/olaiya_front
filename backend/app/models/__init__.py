"""模型包。被 init_db 延迟导入以完成表注册。"""

from . import evidence, ingredient, product  # noqa: F401
