# 护肤品功效证据对比：ModelScope 私有部署

首轮使用独立单页，复用现有数据库和接口。正式站默认构建仍是原有页面；设置 `VITE_APP_MODE=showcase` 时构建展示版。Dockerfile 始终构建展示版，并在单个 CPU 进程上监听 7860。

## 当前展示主线与指数方法

当前主线为「选 A/B 两款产品 → 看八方向证据指数 → 点击贡献成分 → 查看原始来源」。默认两组真实案例不变。主页面不展示聊天或圆桌，确定性计算不调用模型；“找相似产品”仅在打开辅助入口时请求候选。

新增 `GET /api/products/{id}/capability-profile`，方法版本为 `evidence-index-v1`。八个方向固定为保湿、抗皱、修护、舒缓、抗氧化、美白、控油祛痘、焕肤；指数为每个成分在该方向的最高合格证据权重之和，来源数按证据 ID 去重。返回贡献明细、原始来源、备注、排除原因和浓度资料覆盖。空资料返回 `no_evidence`／`score=null`，未评级返回 `unrated`／`score=null`，真实零权重保留 `scored`／`score=0`。

主指数只使用合格论文和既有低强度工具书资料。分类、法规、安全、供应商、专利、白皮书、口服与未评级论文不计分；工具书强度超过既有 0.3 上限时拒绝计入，不擅自改写原权重。体外、动物和综述保留间接性，复方等适用限制保留在备注。相同成分同方向取最大；同一来源关联不同成分时，来源数量仍只计一次，指数不是独立研究数量或临床效果。

浓度不乘进主指数。披露锚点优先于估计；位次未知时不使用存量区间推测浓度。文献浓度缺失与产品浓度未知分别显示，进一步对照复用既有剂量判定。未知值不补零，不输出百分制总分、有效率或性价比结论。两款产品、八方向共用一套图表刻度。

本次只新增读取与聚合服务，不新增数据库列或 `EvidenceType`，SQLite/PostgreSQL 均无需迁移；原有指纹、排行榜与圆桌接口口径保持兼容。固定数据集提交不变，无需重新上传数据库或模型。

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

检查两组案例、双产品搜索、统一刻度、点击方向联动贡献、原文链接与证据抽屉、只看差异／共有／完整表、同单位价格图、缺价／缺索引／未评级／真实零值、过期搜索和画像响应、390px 手机与 ModelScope 内嵌宽度。确认首屏没有模型调用。`/api/health` 不调用模型；`roundtable_configured` 仅表示原有模型配置存在，不是本页面的功能依赖。

上线后核验首页、统计、两个案例和嵌入检索；记录重启前后的数据统计／快照版本，重启后再次检查。模型权限满足时再验收一次完整四角色圆桌和真实引用。

私有空间的浏览器访问需要所属账号登录。SDK 自动化通过平台提示的专用地址 `https://studio-weijiewu-yanjian-ingredient-compare.api-inference.modelscope.net` 携带 Bearer 凭证；普通 `.ms.show` 地址不接受 SDK Token 导航。浏览器产物验收可经认证的 SDK 请求转发真实线上 HTML、静态资源与 API，不将其误报为已经验收了未登录的用户导航。

## 首轮验证记录（2026-10-17）

- 后端全量：809 通过、1 跳过；前端逻辑：4 通过；展示版浏览器：6 通过；原站浏览器回归：12 通过。
- 原站与展示版生产构建通过；390px 手机宽度无横向溢出，截图检查后移除了展示版的背景模糊，避免移动端绘制空白。
- 从私有数据集固定提交下载并校验资产，首次安装、重复启动与数据库保留检查通过。
- 用户完成邮箱验证后，真实云模型四角色调用通过。展示版使用事实编号选择，并将文献核对对象限制为选定产品实际含有且有资料的成分。

## 功效证据对比改版验证（2026-10-17）

- 后端全量 817 通过、1 跳过；覆盖同成分最高权重、重复／共享来源、各资料通道排除、口服场景、工具书低强度、真实零值、无资料、未评级、浓度独立、无效权重和固定查询数。
- 展示版 9 项浏览器用例通过，原站 12 项浏览器回归通过，前端逻辑 7 项通过；验证了 A/B 搜索、迟到响应、统一刻度、单侧失败、来源抽屉、同产品对照、键盘操作和候选按需加载。
- 桌面首屏可见两产品与八方向；手机无横向溢出。搜索初次加载与输入的竞态已修复，初始产品资料返回不再清空正在输入的关键词。


## SkinSort 参考界面迭代（2026-10-17）

本次只改展示版前端和说明：连续双列、参考产品图、分段标题、右侧目录、滚动身份条、共享成分紫色高亮、列表／紧凑视图及更多真实案例。功效先展示四方向，可展开全部八方向；按方向定位下方贡献成分。指数算法、后端 API、数据快照和免费 CPU 配置不变。

四款演示图精确对应已有成分来源页，元数据含出处、图片地址和 SHA-256；不能据图片推断现售包装、规格或版本。不加入无来源的评价、安全标签或成品功效。测试覆盖真实图片加载、首屏功效入口、目录／身份条、共享成分与差异筛选、手机及原有竞态场景。视觉证据见根目录 `design-qa.md` 与 `docs/design/`。

本轮本地验证：全量 pytest 817 通过、1 跳过；展示版浏览器 10 项、原站浏览器 12 项和前端逻辑 7 项通过。原站与展示版生产构建通过。参考图片哈希校验与待提交文件检查通过，`web/` 保持默认原站构建。

## 全库产品地图版本（2026-10-18）

默认展示入口改为产品地图，双列对比通过地图选择两款或 `?compare=<A>,<B>` 进入。`web/` 仍构建默认原站；Docker继续构建展示版，CPU资源不变。新增只读 `GET /api/product-space`：一次返回全库轻量记录、八方向原始指数/状态与可选冻结坐标，固定四条SQL，gzip与ETag/304，60秒有界缓存并考虑SQLite主文件/WAL签名及实际绑定数据库身份。画像详情仍按需读取原API。

DB和Faiss快照继续固定 `0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef`，不重新上传或覆盖。新增约211KB的 `product-space-layout.json` 仅上传到原私有数据集的独立版本：

| 变量 | 固定值 |
|---|---|
| `CFZ_PRODUCT_SPACE_LAYOUT_REVISION` | `2ac1d405caa709c9934c57bf3c6070540f18f4ff` |
| `CFZ_PRODUCT_SPACE_LAYOUT_SHA256` | `4a2a3a4048b9b5d6cc457e3ba774cd7583c4050808ca36066d267eb0787287b2` |

bootstrap在移除下载Token之前，下载上述独立固定版本，校验SHA后原子写入 `/mnt/workspace/cfz/layouts/<revision>/product-space-layout.json`，给worker注入 `CFZ_PRODUCT_SPACE_LAYOUT_PATH`。后续启动读已有校验产物，无需Hub；异常只关闭投影，保留全库原始证据坐标。API再核对catalog签名和源DB快照版本，不能给不匹配产品编造位置。

UMAP/Numba及scikit-learn只用于离线脚本，不进入Docker运行依赖。重建命令示例（所有Python命令仍使用项目venv）：

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 NUMBA_NUM_THREADS=1 \
PYTHONPATH=/tmp/cfz-atlas-analysis-deps .venv/bin/python data/tools/build_product_space.py \
  --database data/models/showcase-runtime-test/0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef/cfz.db \
  --index-dir data/models/showcase-runtime-test/0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef \
  --output data/models/product-space/layout-v1.json \
  --snapshot-revision 0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef
```

离线依赖固定在 `data/tools/requirements-product-space.txt`，可用 `.venv/bin/python -m pip install --target /tmp/cfz-atlas-analysis-deps -r ...` 放入隔离目录；不修改Web主环境，不安装torch。坐标、数据库、索引及依赖目录不提交。CLI独立重建与审核版本的完整产物SHA一致；相同向量不随机抖动。

验证：832项pytest通过、1跳过；13项前端逻辑、7项地图浏览器、10项对比页浏览器、12项原站浏览器通过。三个视窗与空库由第三轮新专家独立复验；完整审核见 `docs/产品地图-设计与审核.md`。上线时检查3749/3749坐标、八维NULL保留、全库搜索、重叠点、任意两款、来源、原始向量候选，以及重新部署后数据和坐标签名不变。
