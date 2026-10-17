# 成分对照台：ModelScope 私有部署

首轮使用独立单页，复用现有数据库和接口。正式站默认构建仍是原有页面；设置 `VITE_APP_MODE=showcase` 时构建展示版。Dockerfile 始终构建展示版，并在单个 CPU 进程上监听 7860。

## 资源与数据

- 私有创空间：`WeijieWu/yanjian-ingredient-compare`，创建时选择平台返回的免费 `platform/2v-cpu-8g-mem`。调整硬件前重新查询可用资源，不自动切换付费实例。
- 私有数据集：`WeijieWu/yanjian-showcase-data`。快照包含 SQLite 在线备份、两组 Faiss 文件及 ID 映射、SHA-256 清单；没有模型权重或原始采集文件。
- 首版数据集固定提交：`0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef`。文件写入 `/mnt/workspace/cfz/<revision>/`，重启校验索引和数据库完整性，不覆盖现有数据库；本地安装完整时重启不依赖 Hub 下载。
- 平台持久目录不代替备份。保留私有数据集版本，不改名或迁移空间来试验持久性。

导出新版本（新建目录，不覆盖旧快照）：

```bash
.venv/bin/python -m deploy.export_snapshot \
  --output data/models/showcase-snapshots/<新版本> --version <新版本>
```

若旧索引仍引用已删除实体，默认拒绝导出。人工检查后可显式加 `--prune-deleted-ids`，只重写导出副本，保留有效行的向量及 ID 对应，并在清单记录移除 ID。不重算嵌入或修改原数据库、原索引。

用 `modelscope_hub.HubApi(token=...)` 创建／检查私有数据集并上传快照目录；确认 `visibility=private` 后才上传。使用返回的完整 `commit_id` 固定版本，不能用 `master` 代替。

## 变量与 Secrets

| 名称 | 存放位置 | 用途 |
|---|---|---|
| `CFZ_SNAPSHOT_REPO` | 变量 | 私有数据集标识 |
| `CFZ_SNAPSHOT_REVISION` | 变量 | 数据集完整 40 位提交 ID |
| `CFZ_SNAPSHOT_MANIFEST_SHA256` | 变量 | 原始 manifest.json 的 SHA-256 |
| `CFZ_SHOWCASE_DATA_DIR` | 变量，可省略 | 默认 `/mnt/workspace/cfz` |
| `CFZ_SNAPSHOT_TOKEN` | Secret | 下载私有数据集，启动 Web worker 前从其环境移除 |
| `CFZ_LLM_CHANNEL` | 变量 | `cloud` |
| `CFZ_CLOUD_BASE_URL` | 变量 | `https://api-inference.modelscope.cn/v1` |
| `CFZ_CLOUD_MODEL` | 变量 | 首版选用列表实际返回的 `Qwen/Qwen3.5-35B-A3B` |
| `CFZ_CLOUD_ENABLE_THINKING` | 变量 | `false`，避免思考文本消耗角色发言预算 |
| `CFZ_ROUNDTABLE_GROUNDED` | Docker 默认／变量 | `true`；模型只选择已有事实编号，后端输出对应工具事实 |
| `CFZ_CLOUD_API_KEY` | Secret | 通过权限验证后使用的模型调用凭证 |

平台管理 Token 不放进前端、Git remote、Docker 构建参数或代码。数据集与模型的授权用途分别核验；模型列表可读不代表生成请求有权限。

2026-10-17 首次验证：平台身份、创空间创建、私有数据集上传成功；模型生成请求先返回 403，用户完成邮箱验证后真实四角色圆桌调用成功。验收发现自由生成会补出工具未提供的功效门槛，因此展示模式启用事实编号选择：模型选择重点，后端只输出已有工具事实；无法解析的选择回退到工具事实，最终呈现资料核对摘要，保留成品功效的不确定性。普通站默认圆桌行为保持兼容。

## 代码同步与发布

验证后提交并立即推送 GitHub `master`。从对应提交提取以下白名单到独立的创空间 Git checkout，再普通提交／推送 `master`，不强推、不合并创空间历史进源仓库：

- `Dockerfile`、`.dockerignore`、`backend/app/`、`data/seed/`、`deploy/`。
- `frontend/src/`、`frontend/public/`、`frontend/index.html`、依赖清单／锁文件、Vite／Tailwind／PostCSS 配置。
- 将 `deploy/STUDIO_README.md` 复制为创空间根目录 `README.md`。

不复制 `.env`、`.venv*`、`node_modules`、`cfz.db`、`data/raw`、索引与权重、其他未跟踪文件。Git 用临时 credential helper 或 askpass 获取凭证，不把 Token 嵌入 remote URL。

使用 `POST /openapi/v1/studios/WeijieWu/yanjian-ingredient-compare/deploy` 发布；轮询空间状态，并检查 `logs/build` 与 `logs/run`。Dockerfile 的运行时依赖单独锁定在 `deploy/requirements.txt`，不安装 torch 或数据采集／OCR 依赖。

## 验收

```bash
.venv/bin/python -m pytest
node --test frontend/tests/showcase.test.mjs
npm --prefix frontend run build
VITE_APP_MODE=showcase npm --prefix frontend run build -- --outDir /tmp/cfz-showcase-web
```

本地用 `tmux` 启动 `VITE_APP_MODE=showcase npm --prefix frontend run dev -- --host 0.0.0.0 --port 5175`，API 仍通过 Vite 代理访问固定 8008。浏览器测试复用项目已有 Playwright 环境：

```bash
PYTHONPATH=/tmp/pwenv/lib/python3.11/site-packages \
CFZ_E2E_BASE_URL=http://127.0.0.1:5175 \
.venv/bin/python -m unittest frontend.e2e.test_showcase -v
```

检查两个案例、全库搜索、两种检索、同单位价格排序、证据抽屉、缺价／缺索引、过期搜索响应、切换产品清理圆桌、SSE 中断及 390px 手机布局。`/api/health` 不调用模型；`roundtable_configured` 仅表示配置存在，不能用它宣称模型已通过真实调用。

上线后核验首页、统计、两个案例和嵌入检索；记录重启前后的数据统计／快照版本，重启后再次检查。模型权限满足时再验收一次完整四角色圆桌和真实引用。

## 首轮验证记录（2026-10-17）

- 后端全量：809 通过、1 跳过；前端逻辑：4 通过；展示版浏览器：6 通过；原站浏览器回归：12 通过。
- 原站与展示版生产构建通过；390px 手机宽度无横向溢出，截图检查后移除了展示版的背景模糊，避免移动端绘制空白。
- 从私有数据集固定提交下载并校验资产，首次安装、重复启动与数据库保留检查通过。
- 用户完成邮箱验证后，真实云模型四角色调用通过。展示版使用事实编号选择，并将文献核对对象限制为选定产品实际含有且有资料的成分。
