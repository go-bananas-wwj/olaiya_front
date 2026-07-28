# AGENTS.md —— 成分真言

欧莱雅黑客松「信任守护师」赛题项目：敢说真话的化妆品成分核验平台（每条功效断言挂真实文献）。

## 环境

- Python 3.11，venv 在 `.venv/`；**统一用 `.venv/bin/python` 执行**，不用全局 python
- pip 已配清华镜像；Node v20 + npm（registry 已设 npmmirror）
- 开发期 SQLite（`cfz.db`，git 忽略），切 PostgreSQL 只改 `CFZ_DATABASE_URL`
- 测试：仓库根目录 `.venv/bin/python -m pytest`（应全绿）
- Playwright 采集环境：`/tmp/pwenv/bin/python`（chromium 已装，参数 `--no-sandbox --disable-dev-shm-usage`）

## 后台服务（统一 tmux，不用 nohup）

- Web 服务端口统一 **8008**（8000 被其他程序占用）
- 启动：`tmux new-session -d -s cfz-web -c /root/workspace/olaiya "PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8008"`
- 查看：`tmux ls` / `tmux attach -t cfz-web`（`Ctrl+B` 后按 `D` 退出不中断）

## 目录约定

```
backend/app/        FastAPI 应用（models/ services/ main.py）
backend/tests/      pytest（TDD：先写失败测试再实现）
data/
├── models/         ★ 模型权重与训练产物（大文件不进 git）
│   ├── embedding/     句向量模型（BGE-M3 等）
│   ├── llm/           对话大模型（Qwen 等）
│   └── ingredient2vec/ 自训练成分向量
├── raw/            原始采集数据（git 忽略）
├── seed/           手工核实的种子数据（进 git，文献必须真实可查）
├── research/       研究产出的证据 JSON（机验后入库）
├── loaders/        数据加载器（幂等，CLI 见各文件 docstring）
└── tools/          采集器/核验器/推断执行器
frontend/           React+Vite 源码（build 到 web/ 由 FastAPI 托管）
web/                前端构建产物（进 git）
```

**模型权重、数据集一律放 `data/` 下对应目录**，权重在 `data/models/`，不硬编码路径进代码。

## 数据铁律（不可违反）

1. 功效断言必须挂真实证据（DB 层 NOT NULL + SQLite 外键强制）；文献必须真实可查，禁止编造
2. paper 类证据入库前必须过机器核验（`data/tools/verify_evidence.py`，PMID→NCBI 标题比对）
3. 推断浓度是估计值，输出与展示必须带「估计」语义；无官方降序成分表的产品不做浓度推断，不伪造位次
4. 不爬取天猫/京东/美丽修行等明确禁止的平台；采集礼貌延时（≥4s/页），触发限流立即熔断冷却
5. 弱证据（口服/动物/体外/复方）必须在 note 字段如实标注；断言另有结构化列 `evidence_level`/`evidence_strength`（规则集中在 `app/services/evidence_level.py`，回填用 `data/tools/backfill_evidence_level.py`），拿不准一律落 `unknown`，禁止猜测

## Git 约定

- 提交格式 `type: 中文描述`，type ∈ feat / fix / test / chore
- 每个任务一个提交；工作区保持干净（`cfz.db`、`data/raw/`、`.superpowers/`、`node_modules/` 已忽略）
