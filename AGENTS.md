# AGENTS.md — 成分真言（颜鉴）项目初始化

## 项目使命

这是欧莱雅美妆科技黑客松「信任守护师」赛题的参赛项目：一个以真实、可追溯证据核验化妆品成分与功效宣称的平台。对用户的核心承诺是：**每个结论都能追到来源；不能确定时明确说不能确定。**

不要把安全评估、法规分类、原料商营销资料或浓度估计写成临床功效事实，也不要为补齐产品信息而猜测。

## 先读什么

- `成分真言-最终总纲-v4.md`：项目定位、能力边界、演示口径和长期路线的唯一基准。
- `成分真言-需求文档-v1.0.md`、`成分真言-设计方案-页面功能-v2.md`：产品需求与页面体验。
- `成分真言-实施计划-*.md`：已落地功能的接口、验收与实现上下文；旧计划的待办不是自动授权的新需求。
- `成分真言-前端需求-性能顺接与交互修复.md`：前端接口契约、竞态防护和展示口径。
- `docs/项目报告.md`、`docs/路演脚本.md`：对外材料，改动产品表述时保持一致。

发生冲突时，以用户最新指令为最高优先级；其次以本文件的数据铁律和最终总纲为准；再参考历史实施计划。

## 技术地图

```text
backend/app/       FastAPI + SQLAlchemy：模型、服务、API、数据库初始化
backend/tests/     pytest；每个测试使用独立临时 SQLite 库
frontend/          React 18 + Vite + Tailwind + HashRouter 源码
web/               前端构建产物，由 FastAPI 托管，须随前端变更提交
data/seed/         经人工核实、可提交的种子数据
data/research/     研究与核验结果 JSON；入库前仍须走相应校验
data/loaders/      幂等入库脚本
data/tools/        采集、证据核验、评测、索引等工具
data/models/       模型和索引产物；权重与大文件不得提交
vision_service/    AI 生图检测 sidecar（DINOv2 + 线性探针）
lab/               线框与视觉实验，不等同生产前端
```

开发期使用 SQLite（默认 `cfz.db`）；只需设置 `CFZ_DATABASE_URL` 即可切到 PostgreSQL。配置统一在 `backend/app/config.py`，不要在业务代码里硬编码环境路径、模型地址或密钥。

## 运行与验证

- Python 版本为 3.11，**所有 Python 命令使用 `.venv/bin/python`**，不要调用全局 `python`。
- 后端测试：`.venv/bin/python -m pytest`
- 前端构建：`npm --prefix frontend run build`（会更新需提交的 `web/`）
- 本地 Web 服务固定使用 8008（8000 已被占用）：
  `tmux new-session -d -s cfz-web -c /root/workspace/olaiya "PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8008"`
- 视觉 sidecar 使用 `.venv-llm`、仅监听 8101：
  `tmux new-session -d -s cfz-vision -c /root/workspace/olaiya ".venv-llm/bin/python -m uvicorn vision_service.app:app --host 127.0.0.1 --port 8101"`
- 不用 `nohup` 管理服务。使用 `tmux ls` 查看，`tmux attach -t <name>` 诊断。
- 需要重建向量索引时，主环境不要安装 torch：
  `TORCH_DEVICE_BACKEND_AUTOLOAD=0 .venv-llm/bin/python data/tools/build_embeddings.py`

修改后按风险运行相关测试；涉及后端模型、API、加载器或共享服务时跑全量 pytest，涉及前端时构建并做针对性页面验收。先写会失败的测试，再实现最小改动。

## 数据铁律（不可违反）

### 证据与表述

1. 功效断言必须绑定真实、可查的证据；数据库层的非空与外键约束不得绕过。`paper` 证据入库前必须经 `data/tools/verify_evidence.py` 用 PMID 和 NCBI 标题机器核验，禁止编造论文、PMID、标题或结论。
2. 证据强度与功效族通过 `app/services/evidence_level.py`、`app/services/efficacy_canon.py` 的既有规则处理；拿不准为 `unknown`，弱证据（口服、动物、体外、复方）必须在 `note` 如实说明。
3. 浓度推断永远是「估计」。只有官方降序成分表才可推断；位次与 1% 线区间是官方事实，应优先展示，百分比区间是次级信息。无有序表时不伪造位次、浓度或剂量结论。
4. 安全评估、法规限制和官方功能分类不是功效实证。法规/安全断言不参与功效指纹；防腐和法规类不混入功效族聚合。

### 成分与来源匹配

1. 成分中文名只能来自 `data/seed/inci_cn_map.json` 的 IECIC 2021 映射；不得用 LLM 或翻译补名。未命中保留原文。
2. 别名只能使用经 PubChem 同 CID 双向核验的 `data/seed/usan_inci_alias.json`，并且只用于匹配，不能改变中文名来源。多 CID 或族类条目一律不猜。
3. 加载器必须幂等，默认不覆盖既有人工核订数据；例外仅限代码中明确、可审计的核订修正模式。

### 各证据通道的边界

- **CosIng**：是欧盟官方申报功能分类，证据类型为 `database`；文案必须写「功能分类」且注明“非功效实证”，不说“证明”或“临床”。只映射语义明确的功能码。
- **NMPA**：功效宣称法定类别只入法规证据，不建成分断言；限用组分可建「法定限用」断言并明确“法规限值，非功效起效浓度”。族类条目没有明确 `match_inci` 时不匹配。
- **CIR / SCCS**：CIR 是行业自评意见，不是监管限值；机器提取的 CIR 浓度必须人工回读 PDF 核订后才可入库。SCCS 保留分场景结论，只有明确、安全且适用的上限才可回填；“不安全”结论如实展示且不回填限值。
- **专利、原料商、工具书**：专利和供应商资料必须标注“未经同行评议”，强度保持 `unknown`；供应商断言不计入功效指纹。工具书 OCR 用途句是行业参考、非原始研究，按既有 `book_loader.py` 护栏入库，强度固定为低；工具书断言可参与指纹。
- **配方典型用量**：仅作配方实践参考，不是官方限值或功效起效浓度；解析结果只在缺失时补充，含公式或没有数值的行不猜测。
- **OCR**：扫描书 OCR 只能直接使用已验证的名称、正文用途叙述和单一数值。表格限值、化学式、结构式不可直接抽取；双栏页面先重排，任何异常数字、错字、断句或拉丁名都要回看原图并核验，无法核实则跳过。

### 采集与市场数据

1. 不抓取天猫、京东、美丽修行等禁止平台；采集间隔至少 4 秒，限流后立即停止并冷却。先检查 robots 与站点条款。
2. 修丽可价格必须保留现行性与匹配说明；值得买的 `value_ratio` 只能称「值率（投票）」而非好评率。规格、色号或套装存在歧义时标低置信度，不入库。
3. 模型权重、原始采集数据和数据集一律放在 `data/` 对应目录；不得提交大模型权重或 `data/raw/` 内容。

## 实现约定

- 优先复用现有服务与加载器，避免把业务规则复制到路由或前端。数据库加列通过 `app.db.ensure_additive_columns` 做兼容迁移。
- API 输出要保留不确定性、来源、`note`、证据层级和估计语义；前端不得将保守字段重新渲染成确定性承诺。
- React 页面处理筛选、搜索、分页、路由切换与“加载更多”时要防过期响应覆盖和重复追加；不要破坏已有 API 契约。
- 新数据源或新枚举需要同时补模型、加载器、测试、展示文案与 PostgreSQL 迁移说明；新增 `EvidenceType` 时 PostgreSQL 要显式 `ALTER TYPE`。

## Git 与工作区

- `origin` 是 `git@github.com:go-bananas-wwj/olaiya_front.git`，默认分支 `master`。开始前先查看工作区；保留不相关或未跟踪文件，绝不擅自清理。
- 一个用户任务一个聚焦提交。提交格式：`feat: 中文描述`、`fix: 中文描述`、`test: 中文描述` 或 `chore: 中文描述`。
- 完成代码或文档改动后，先验证，再提交并立即 `git push origin master`；不要遗留未推送提交。
- `cfz.db`、`data/raw/`、`.superpowers/`、`node_modules/` 等本地生成物不提交。前端源码有变更时，更新并提交 `web/` 构建产物。
