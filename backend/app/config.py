"""全局配置。环境变量前缀 CFZ_，例如 CFZ_DATABASE_URL 覆盖数据库地址。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CFZ_", env_file=".env", extra="ignore")

    # 开发期默认 SQLite 文件库；切换 PostgreSQL 只需改环境变量
    database_url: str = "sqlite:///./cfz.db"

    # Faiss 相似索引目录（data/tools/build_embeddings.py 产物）；相对路径按仓库根目录解析
    faiss_index_dir: str = "data/models/embedding/faiss"


settings = Settings()
