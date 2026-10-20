# 护肤品功效证据对比：ModelScope 私有部署

首轮使用独立单页，复用现有数据库和接口。正式站默认构建仍是原有页面；设置 `VITE_APP_MODE=showcase` 时构建展示版。Dockerfile 始终构建展示版，并在单个 CPU 进程上监听 7860。

## 当前展示主线与指数方法

改版主线为「产品空间 / 按需选品 / 两款对比」。三维保留原3749条语义向量与坐标；补充记录无真实向量时不补点。默认突出核验面霜，需求入口进入二维价格／单方向证据图。品牌和整件预算只改变突出状态，不改变坐标尺度；同单位分组、至多4款候选、两款对比往返。旧八方向完整证据空间和原API保持兼容。实际发布状态与覆盖见[实施验收](需求选品地图-实施与验收.md)。

新增 `GET /api/selection-map`，接收 `category/efficacy/unit/brand/max_package_price`；后端集中做来源资格、价格换算、指数与固定轴范围。完整标签与知识库匹配分别记录；部分表不进入正式主图。按月目录保留月份及日龄范围，不将读取日或月初冒充报价采样日。

新增 `GET /api/products/{id}/capability-profile`，方法版本为 `evidence-index-v1`。八个方向固定为保湿、抗皱、修护、舒缓、抗氧化、美白、控油祛痘、焕肤；指数为每个成分在该方向的最高合格证据权重之和，来源数按证据 ID 去重。返回贡献明细、原始来源、备注、排除原因和浓度资料覆盖。空资料返回 `no_evidence`／`score=null`，未评级返回 `unrated`／`score=null`，真实零权重保留 `scored`／`score=0`。

主指数只使用合格论文和既有低强度工具书资料。分类、法规、安全、供应商、专利、白皮书、口服与未评级论文不计分；工具书强度超过既有 0.3 上限时拒绝计入，不擅自改写原权重。体外、动物和综述保留间接性，复方等适用限制保留在备注。相同成分同方向取最大；同一来源关联不同成分时，来源数量仍只计一次，指数不是独立研究数量或临床效果。

浓度不乘进主指数。披露锚点优先于估计；位次未知时不使用存量区间推测浓度。文献浓度缺失与产品浓度未知分别显示，进一步对照复用既有剂量判定。未知值不补零，不输出百分制总分、有效率或性价比结论。两款产品、八方向共用一套图表刻度。

本次新增可空 `products.source_key VARCHAR(300)` 及唯一索引，保存公开来源命名空间、官方商品码及完整原文/法定版本签名；同官方码配方或备案改变时拒绝静默合并。`ensure_additive_columns` 幂等补列，旧数据保持NULL，无新增 `EvidenceType`。PostgreSQL可显式执行：

```sql
ALTER TABLE products ADD COLUMN IF NOT EXISTS source_key VARCHAR(300);
CREATE UNIQUE INDEX IF NOT EXISTS ix_products_source_key ON products(source_key);
```

采集原件不提交。可审计事实保存在 `data/research/selection_catalog_20261020.json`，既有记录复用在 `selection_legacy_audit.json`；在可写的SQLite备份上运行 `PYTHONPATH=backend .venv/bin/python -m data.tools.build_selection_catalog`，同时导出部署所需 `data/seed/selection_catalog.json`。默认不导入部分表成分、不模糊匹配旧版本。旧价格加载器要求真实完整日期；缺日期、只有月份或未来日期不改写入库时间。

发布新数据库/索引/映射一致快照并固定资源版本。`rebind_product_space` 先验证旧产品成分/位次关联完全一致，才保留旧语义坐标、重绑新快照，并离线重建证据PCA；新产品无嵌入时坐标为空。原快照和原布局保持可回滚，不覆盖已有持久目录。

## 资源与数据

本轮为**覆盖预览**，不是全计划最终验收：新增官网目录280款、完整官方标签17款；默认严格保湿面霜ml图11款，20款门槛未过。新快照 `15b764ae05d73ffe934b1d2d25d3ca8651992770`，清单SHA-256 `26099127c043ae6cc65d75870574ea63e40780f08123cc7a63c9e7a98e82acd2`；布局固定提交 `75a1e44e709e241ecb44ff937bf2fa0da2a4caa6`，文件SHA-256 `24add5abfbff62373d0a3b92bc7d19ddbe9a3d5d58fe2de709d69ee2dfcd2b17`。原3749条语义坐标、4个案例画像逐项验证不变，新增280条无向量记录保留搜索入口，不补坐标。

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

## 全库产品地图版本（2026-10-18，历史首轮）

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

## 双核心清新重设计（2026-10-18—19，北京时间）

顶部“产品地图 / 两款对比”为同级入口。地图使用真实数量集合、较大参照/候选节点与编号，前景白环减少相邻文字混淆；不能保证真实重叠坐标完全不遮挡，保留逐款列表。手机默认页面内详情，避免强制弹窗。对比页紧凑身份卡后完整八方向，两产品共用刻度；任意更换、案例和地图往返同步URL与父状态。

新增 `GET /api/products/{id}/space-neighbors?limit=3`（1—12），方法 `evidence-neighbors-v1`，从现有 `evidence-index-v1` 轻量画像计算。至少三个已评分参考方向且有正贡献，候选覆盖同一组方向，按全库尺度归一化均方根差排序；未知不补零、同距按ID排序，不显示临床相似百分比。原4096维组成检索及L3接口不变。接口不可用仅对应候选区报错，两款比较仍可验收。

本轮无数据库或资源迁移：快照仍为 `0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef`，冻结投影仍为独立数据集提交 `2ac1d405caa709c9934c57bf3c6070540f18f4ff`，布局SHA `4a2a3a4048b9b5d6cc457e3ba774cd7583c4050808ca36066d267eb0787287b2`。不要重新上传数据库/权重，继续私有免费CPU。

本地838项pytest通过/1跳过、16项前端逻辑、23项展示浏览器、12项原站浏览器通过；两种生产构建通过。严格视觉门槛8.5，实际四轮7.9→8.3→8.4→8.6，通过后冻结视觉；见[验收记录](双核心重设计-验收记录.md)。

发布仅同步白名单源码及部署文件；Studio README改为双核心口径。构建后分别核验真实云端HTML/API、两种近邻、任意A/B/返回保持、两个案例、来源、手机/内嵌布局、匿名401，再重启检查固定数据及布局签名一致。私有页面的自动浏览器验收通过仅向本空间域名附加授权的HTTP转发完成，使用真实云端响应，不伪造接口；这不等于已核验所属账号登录后的平台外层页面。

## Embedding Projector版本（2026-10-19）

当前展示版复刻Google Embedding Projector的三栏、酒红顶栏、白底点云与点选联动；手机侧栏改抽屉。新源码见 `frontend/src/showcase/projector/`；原站仍以默认构建提交 `web/`，Docker用 `VITE_APP_MODE=showcase`。

布局资源新增v2，原二维坐标完全保留；API新增 `coordinates_3d`／`pca_coordinates` 与分模式状态。UMAP3D与PCA来自原4096维，不补随机Z；某模式无坐标时明确不可用。相似接口原默认5不变，上限扩100，近邻始终读取快照原向量，旋转或隔离不重定义排名。前端Three.js仅在浏览器绘制，CPU运行时不拟合UMAP／PCA。

发布需成对更新以下两个已有变量（非Secret）：

| 变量 | 新固定值 |
|---|---|
| `CFZ_PRODUCT_SPACE_LAYOUT_REVISION` | `ea284a4798743d3c11780983df3c24c95247e9aa` |
| `CFZ_PRODUCT_SPACE_LAYOUT_SHA256` | `e209bbcd009a527c1b6bd85f1c314abc04a59919519a2ea56fd1b31db4e644f4` |

数据库快照仍为 `0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef`，不要改成布局revision；文件仍名 `product-space-layout.json`，共735143字节，已在私有数据集上传并重新下载校验。持久路径为 `/mnt/workspace/cfz/layouts/<新revision>/`。旧布局不覆盖，重启须复用已校验新布局。

源index SHA为 `1bfa3201e58d36c4c275389e0418dab86627fcff5c65b98be4a1314ebba928da`，对应原快照3749条。启动器强制使用同快照索引；本地验收也设置 `CFZ_FAISS_INDEX_DIR=data/models/showcase-snapshots/20261017-v1`，不拿3776条开发索引替代。数据库、模型与原始采集数据均不随源码提交。

本地862项pytest通过/1跳过，32项逻辑、25项展示浏览器通过；原站和展示构建通过，原站12浏览器通过。严格视觉8.7通过，数据／UX／renderer／新发布专家无P0/P1/P2。源参考、实际截图和问题关闭记录见[本轮验收](Embedding-Projector-实施与验收.md)。

云端验收须读取真实HTML和API：3749款及三个空间计数、原二维与四款画像不变、默认100近邻与原索引同版、3D真实旋转、2D、点选灰橙玫红、隔离／恢复／清除、两款任意ID／两个案例／来源、390及834布局、匿名401。再部署同一版本验证容器重建后复用新布局，固定签名与数据不变。私有浏览器可使用仅附加本空间域授权的真实HTTP转发，不能mock数据或声称已核验平台外层所属账号登录流程。


## 产品身份与独立证据空间修正（2026-10-19）

新增只读接口 `GET /api/product-space/evidence` 和 `GET /api/products/{id}/evidence-space-neighbors?limit=100`。旧语义地图、similar、space-neighbors及两款capability-profile契约保持兼容。证据新方法 `evidence-space-v1` 复用 `evidence-index-v1`，只纳入八个方向均为scored且分值有效的39款；真实零保留，无资料／未评级不补零。全库同轴尺度为 `[4.25,6.5,4.6,2.8,2.05,3,3.35,3]`，按八维缩放差的均方根计算近邻。该距离不是功效评分，指数不乘未知浓度。

v3小型布局bundle附带独立证据PCA，完整保留v2旧语义points、UMAP3D与PCA坐标。下载／启动机制不变，仅更新以下已有非Secret变量；数据库与Faiss快照仍固定原版本，不重新上传或覆盖。

| 变量 | v3固定值 |
|---|---|
| `CFZ_PRODUCT_SPACE_LAYOUT_REVISION` | `153a6d389a44d035bb3950da3bec24d9eafe710c` |
| `CFZ_PRODUCT_SPACE_LAYOUT_SHA256` | `2800c7145879e1055a40583d67380b0cb3e65789bf445dc8719bdac0988bed9d` |

证据坐标还校验八方向几何画像签名、全库尺度和合格ID集合；改变画像的证据／状态变更将关闭证据投影，保留语义地图。仅来源标题文字修改不改变几何画像。HTTP不执行拟合，Docker无需numpy之外新数值依赖／UMAP／torch。

离线构建（输出到忽略目录）例：

```bash
.venv/bin/python data/tools/build_evidence_space.py \
  --database data/models/showcase-snapshots/20261017-v1/cfz.db \
  --base-layout data/models/product-space/layout-projector-v2.json \
  --base-layout-sha256 e209bbcd009a527c1b6bd85f1c314abc04a59919519a2ea56fd1b31db4e644f4 \
  --output data/models/product-space/layout-projector-v3.json \
  --snapshot-revision 0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef
```

产品名保留版本与来源后缀；每条记录ID唯一，但成分文本／向量／投影位置可相同。同位组用计数展开，不去重合并或随机错开。身份、距离说明、竞态、未知状态、窄屏和来源入口的验收见 `docs/产品空间身份与证据模式验收.md`。

## 2026-10-20 点云交互与群组配色

本轮仅发布界面与兼容的投影索引身份字段。数据库快照、Faiss及冻结布局版本保持现有值，不上传或覆盖数据。

- 去掉立方体、网格、轴名、图内技术图例及小字；使用浅雾紫灰背景。
- 原始余弦相似度按百分比降序显示；证据模式为1减既有归一化RMS距离。“筛选数量”决定返回条数。
- 产品点选以640ms平滑聚焦局部，最多四项标签；支持减少动态效果偏好及拖动/键盘/切换/清除时取消动画。手机默认折叠资料卡，图标签避让资料卡。
- `data/tools/build_composition_families.py` 从固定Faiss归一化向量计算8组球面K-means，种子20261020。小型分组文件随前端源码发布，绑定源索引SHA；原始坐标、检索分数和ID映射不改变。群组A–H是统计分组，不标成功效分类。
- 视觉参考：[Embedding Atlas](https://github.com/apple/embedding-atlas)、[Nomic Data Maps](https://docs.nomic.ai/atlas/datasets/data-maps)。私有免费CPU配置不变。

## 2026-10-20 白色页头与纵深显示

本轮前端改为白色通透页头、项目标题与用途介绍优先、删除A–H群组说明。`projectorDepth.mjs`仅将三维显示坐标X/Y/Z按1.12/1.10/2.10展开，并使用真实相机深度控制有界点径／透明度；2D与原始检索保持原样。Docker继续构建展示版，数据库、Faiss、布局及持久目录版本保持现状。验收见`产品空间-白色纵深改版验收.md`。

## 2026-10-20 产品介绍与取消选中

发布兼容的产品详情`presentation`字段与来源绑定元数据：3612条资料、3391个图地址及3597段最多25词社区简介。原缓存时间保持，功效宣称读取原ProductClaim，不将简介写成证据。元数据随`data/seed/`打包，不包含原始HTML，不改数据快照／索引／布局；可由`CFZ_PRODUCT_PRESENTATIONS_PATH`配置。图片缺失或不可访问如实占位。

图上新增“返回全景”，产品卡关闭、空白点击及图内Esc/Home同时清除选择并复位；手机底卡直接识别产品，聚焦点上移避让。验证记录见`产品空间-产品介绍与返回交互验收.md`。
