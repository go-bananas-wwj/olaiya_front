"""全局配置。环境变量前缀 CFZ_，例如 CFZ_DATABASE_URL 覆盖数据库地址。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CFZ_", env_file=".env", extra="ignore")

    # 开发期默认 SQLite 文件库；切换 PostgreSQL 只需改环境变量
    database_url: str = "sqlite:///./cfz.db"

    # Faiss 相似索引目录（data/tools/build_embeddings.py 产物）；相对路径按仓库根目录解析。
    # 默认 Qwen3-Embedding-8B（域内评测成分/功效保真最优，见 data/eval/embedding_compare_report.json）；
    # BGE-M3 对照索引在 faiss/ 根目录，Qwen3-0.6B 在 faiss/qwen3-0.6b/
    faiss_index_dir: str = "data/models/embedding/faiss/qwen3-8b"


settings = Settings()
