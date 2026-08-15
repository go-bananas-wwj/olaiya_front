# AGENTS.md —— 成分真言

欧莱雅黑客松「信任守护师」赛题项目：敢说真话的化妆品成分核验平台（每条功效断言挂真实文献）。

## 环境

- Python 3.11，venv 在 `.venv/`；**统一用 `.venv/bin/python` 执行**，不用全局 python
- pip 已配清华镜像；Node v20 + npm（registry 已设 npmmirror）
- 开发期 SQLite（`cfz.db`，git 忽略），切 PostgreSQL 只改 `CFZ_DATABASE_URL`
- 测试：仓库根目录 `.venv/bin/python -m pytest`（应全绿）
- Playwright 采集环境：`/tmp/pwenv/bin/python`（chromium 已装，参数 `--no-sandbox --disable-dev-shm-usage`）
- 相似检索：主 venv 的 faiss-cpu 只读索引；重建嵌入索引用 `.venv-llm`（torch/transformers，主 venv 不装）：
  `TORCH_DEVICE_BACKEND_AUTOLOAD=0 .venv-llm/bin/python data/tools/build_embeddings.py`
  （BGE-M3 → `data/models/embedding/faiss/`，训练产物不进 git；torch_npu 自动加载会报 libstdc++ 错，纯 CPU 跑须关掉）

## 后台服务（统一 tmux，不用 nohup）

- Web 服务端口统一 **8008**（8000 被其他程序占用）
- 启动：`tmux new-session -d -s cfz-web -c /root/workspace/olaiya "PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8008"`
- 视觉 sidecar（AI 生图检测，端口 **8101**，.venv-llm 运行，模型首次请求时加载）：
  `tmux new-session -d -s cfz-vision -c /root/workspace/olaiya ".venv-llm/bin/python -m uvicorn vision_service.app:app --host 127.0.0.1 --port 8101"`
  主后端 `POST /api/detect-image` 代理转发（`CFZ_VISION_URL` 可改地址），sidecar 不可达时 503 降级
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
├── eval/           域内评测集与跑分报告（build_eval_set.py 生成 qa_eval.json，run_eval.py 出 report.json）
├── loaders/        数据加载器（幂等，CLI 见各文件 docstring）
└── tools/          采集器/核验器/推断执行器/评测器
frontend/           React+Vite 源码（build 到 web/ 由 FastAPI 托管）
vision_service/     视觉 sidecar（AI 生图检测，DINOv2+线性探针，.venv-llm 运行；torch 惰性导入，主 venv 可 mock 跑测）
web/                前端构建产物（进 git）
```

**模型权重、数据集一律放 `data/` 下对应目录**，权重在 `data/models/`，不硬编码路径进代码。

## 数据铁律（不可违反）

1. 功效断言必须挂真实证据（DB 层 NOT NULL + SQLite 外键强制）；文献必须真实可查，禁止编造
2. paper 类证据入库前必须过机器核验（`data/tools/verify_evidence.py`，PMID→NCBI 标题比对）
3. 推断浓度是估计值，输出与展示必须带「估计」语义；无官方降序成分表的产品不做浓度推断，不伪造位次；展示层保守化（2026-08-11 拍板）：位次与 1% 线区域（全量/微量）是官方事实、突出展示，百分比区间估计降级为次级信息不单独突出
4. 不爬取天猫/京东/美丽修行等明确禁止的平台；采集礼貌延时（≥4s/页），触发限流立即熔断冷却
5. 弱证据（口服/动物/体外/复方）必须在 note 字段如实标注；断言另有结构化列 `evidence_level`/`evidence_strength`（规则集中在 `app/services/evidence_level.py`，回填用 `data/tools/backfill_evidence_level.py`），拿不准一律落 `unknown`，禁止猜测；规范功效族列 `efficacy_canonical`（规则在 `app/services/efficacy_canon.py`，回填用 `data/tools/backfill_efficacy_canonical.py`），功效指纹按规范族聚合并排除法规/防腐族断言
6. 成分中文化只用 IECIC 2021 官方映射（`data/seed/inci_cn_map.json`，来源与抽查核对说明在文件 source 字段；PDF 提取 `data/tools/extract_iecic_pdf.py` 需 pdfplumber，生成 `data/tools/build_inci_cn_map.py`），禁止 LLM 机翻成分名；清洗回填用 `data/loaders/inci_cn_loader.py`（幂等，未命中保持原样）。成分别名（USAN 名 / CERAMIDE 2013 更名前旧名 / 其他俗名 → IECIC 键）只用 PubChem 同 CID 双向核验的 `data/seed/usan_inci_alias.json`（多段结构 alias/alias_ceramide/alias_common，构建 `data/tools/build_usan_alias.py`，同 CID 唯一 IECIC 命中才接受、多 CID 拒收，原始响应存 `data/raw/pubchem_usan/`），别名只用于匹配，中文名仍只出自 IECIC 映射；拼写/标点变体走 loader 折叠形唯一命中（数字保留、CJK 保留、损坏 IECIC 键黑名单 `_CORRUPT_IECIC_KEYS` 除外）
7. CosIng 功能分类断言（`data/seed/cosing_functions.json`，官方搜索 API 采集 `data/tools/collect_cosing.py`、构建 `data/tools/build_cosing_seed.py`、入库 `data/loaders/cosing_loader.py`，幂等）是**官方申报功能分类，不是功效实证**：efficacy 一律「功能分类：XX（CosIng 官方申报功能）」，禁止出现「证明/实证/临床」等越界措辞；证据类型 `database`（source="European Commission CosIng"），evidence_level 落 `unknown`；note 固定注明「CosIng 功能字段为官方申报功能分类，非功效实证」并附原功能码；功能码映射只取语义明确子集（FUNCTION_MAP），ambiguous 码一律跳过登记 SKIP_REASONS，未知码绝不猜测映射
8. NMPA 法规层证据（`data/loaders/regulation_loader.py`，幂等）分两层：**功效宣称法定类别**（`data/seed/efficacy_definitions.json`，49 号公告附表 1 定义 + 50 号公告附 1 评价要求）只入 26 条 regulation 证据、**不建断言**（类别层事实不指向成分，挂成分等于伪造）；**安全技术规范 2015 表 3 限用组分**（`data/seed/restricted_ingredients.json`，官方 PDF 抽取 + 人工校正 + 抽查核对，版本为 2015 原始文本）按成分入 regulation 证据 +「法定限用：…」断言（note 注「法规限值，非功效起效浓度」，evidence_level=regulation）+ legal_cap 回填（只回填单一无换算基准上限，已有值不覆盖）；族类条目（「及其盐类/类/配合物」）match_inci 为空绝不猜匹配；法定限用断言 efficacy_canonical 固定「其他」（不走子串规则，防「非防腐用途」字样误归防腐族）；断言挂 regulation 证据不计入功效指纹（fingerprint.py 现有排除规则）
9. 国际安全评估层（`data/loaders/cir_sccs_loader.py`，幂等；断言 efficacy_canonical 一律固定「其他」——安全评估非功效断言；cir_conc/sccs_limit 库函数默认已有值不覆盖，仅 loader 主程序对三个人工核订主数据源开 `allow_correction=True` 核订修正模式，旧值与核订值不同原地改值并记日志）：**CIR**（美国化妆品原料评价委员会，行业自评机构，采集/解析 `data/tools/collect_cir.py`，机器提取的浓度候选必须经人工核订表 `data/tools/review_cir_batch.py` 逐条回读 PDF 原文修正——prose「up to X%」提取存在纯度/毒理剂量/他成分数值误吸，未经核订禁止入库；cir_conc_low/high 语义为行业调查使用浓度区间全品类合计值，取报告表格 Total/range 行（多成分列表格取最新调查年份列），缺失时取驻留/淋洗区间最小低值与最大高值，非安全限值、非功效起效浓度）证据 type=white_paper、措辞「安全评估：现行使用方式和浓度下安全（CIR 评估…）」、note 固定注「行业自评机构意见而非监管限值」、evidence_level 落 unknown；**SCCS**（欧盟消费者安全科学委员会，`data/seed/sccs_opinions.json`，结论句逐条人工核订）证据 type=regulation（官方科学委员会，非法规文本）、sccs_limit 统一回填该意见内最严上限（多场景结论取最严值）、分场景结论完整保留在 scope/note、「不安全」结论不回填 limit 且断言如实措辞「不安全」、scientific advice 单独标注非正式意见；**专利降级通道**：patent 证据措辞保守、note 固定含「专利申请人自述数据，未经同行评议」、evidence_level 强制 unknown（强度 0.2，note 含「体外」等关键词也不走 classify 升级）
10. 价格/口碑市场数据层：**修丽可官网价格通道**（`data/tools/collect_skinceuticals_cn.py`，robots 无 Disallow、sitemap 枚举产品页——loc 是建站机内网 IP 须规范化 host，页面响应头缺 charset 须显式 utf-8；站点陈旧 sitemap lastmod 2023-06，价格现行性须抽查、存疑在 price_note 标注）→ `data/tools/build_skinceuticals_price_seed.py`（slug/中文名双通道规则匹配，多候选依序消歧：剔 Discontinued→剔（…-2）后缀重复行→有序优先→有宣称优先→已有价格优先，仍不唯一记 unmatched 不猜；报告落 `data/research/skinceuticals_price_match.json`）扩展 `data/seed/price_specs.json` → `price_loader` 入库；item 有 `product_id` 走精确通道（校验 brand），防去重合并后 match 串漂移；`products.buy_url` 列经 `app.db.ensure_additive_columns` 幂等补列。**smzdm 口碑/好价通道**：search.smzdm.com robots 全禁（不可爬搜索页），本机 IP 被 WAF 腾讯验证码拦截（不可直连），现行链路为 WebSearch 发现 /p/ 好价页 + FetchURL 读页（/p/ 页 robots 允许，≥4s 间隔），产出 `data/raw/smzdm/{product_id}.json`；match_confidence=low（规格/色号/套装存疑）一律不入库不猜；`GET /api/products/{id}/market` 的 value_ratio 是**值率（smzdm 投票）**，绝不叫好评率、不与渠道商品好评率混淆；日期仅月日的年份按采集日推断并带「估计」语义；官方开放平台 openapi.zhidemai.com 需用户注册 appkey 后可切换（待用户操作）
11. 原料商资料降级通道（`欧莱雅比赛/` 比赛原件，git 忽略；解析 `data/tools/parse_supplier_xls.py` → `data/research/supplier_ingredients.json`，入库 `data/loaders/supplier_loader.py`，幂等）：功效文本是**供应商产品宣称，未经同行评议**——证据 type=supplier（有功效短语的 sheet 一条 evidence，title 不含行数保证幂等）、efficacy 一律「原料商宣称：XX」、note 固定注明「原料商产品资料宣称，未经同行评议」+商品名/类别/生产商、evidence_level 强制 unknown（强度 0.2，不走 classify 升级，同专利降级通道；`data/tools/backfill_evidence_level.py` 对 PATENT/SUPPLIER 一律跳过回填）；复配原料（多组分）断言追加「复配宣称，功效指向复配整体而非单一成分」；功效短语只收 2-8 字纯中文（允许间隔号「·」，长散文不切不猜，prose_skipped 如实计数）、类别列只收能归功效族的值（canonicalize 落「其他」的工艺类型如「水包油」拦截）；供应商中文名只用于匹配（铁律 6 不变）；匹配全程不猜，未命中如实记 `data/research/supplier_match_report.json`；**supplier 断言不计入功效指纹**（fingerprint.py 与 similar_levels 批量指纹同专利一并排除），但 has_evidence/断言总数聚合口径含 supplier，前端徽章需区分口径。SAEnum 存成员名（SUPPLIER），切 PostgreSQL 时需 `ALTER TYPE evidencetype ADD VALUE 'SUPPLIER'`。**配方实践典型用量**（`data/tools/parse_formula_xlsx.py` → `data/research/formula_typical_dose.json`，入库 `data/loaders/formula_loader.py`，幂等）：19 剂型配方实例的 比例% 聚合落 `ingredients.typical_use_low/high`（经 `ensure_additive_columns` 补列），语义为配方实践参考，**非官方限值、非功效起效浓度**，已有值不覆盖；Excel 公式/无数值行跳过不猜。**扫描版 PDF OCR 管线**（`data/tools/ocr_pdfs.py`，PyMuPDF 渲染 250DPI + rapidocr-onnxruntime PP-OCRv4 纯 CPU，流式不存页图，JSONL 追加 + 断点续跑，产物 `data/raw/ocr/` git 忽略）：两本扫描书（化妆品原料技术规格 1074 页 / 化妆品原料手册(新) 422 页）全走 OCR（文本层仅网站水印无价值）；OCR 产物**未经人工抽查核订禁止入库**；核订方式：抽样页 OCR 文本与原页渲染图逐条比对 + 存疑条目（疑似错字/异常数值/非常见原料名）用网上搜索对照该原料的真实资料验证，核实不了的标 unknown 不猜；已知缺陷：页首「化妆品技术在线 HzpOnline」水印行须丢弃、化学式下标丢失（按「估计」语义，且伴随 3→g/6→s/l→1 字形混淆，一律不可解析禁止入库）、手册双栏版面阅读顺序交错（抽取前必须按栏重排）、表格塌缩（≤/≥ 符号系统性误识为「M」「(」等乱码，限值类单元格有漏值实例，**表格限值必须回原页图人工核对，禁止直接从 OCR 抽取**）、结构式/反应式/流程图乱码不可用、**整行/整句断头漏识**（技术规格抽查 5 页中 4 页命中，多在编号条款开头或上标结尾行附近，抽取须校验条款编号连续性，断号/句首悬空即回读原图）、试剂/器皿名为字符级噪声（同词同页可对可错）、拉丁学名有拼写错误实例（须联网校验）、书中数据有年代性（旧国标/旧 ADI，展示标注数据年代口径）；**可信可直接抽取字段**：原料中英文名/别名/条目编号、正文功效/用途/毒性叙述句、正文单数值（分子量/沸点/密度/折射率/含量%，抽样约 40 个数值与原图全对且经联网验证吻合）

## Git 约定

- 提交格式 `type: 中文描述`，type ∈ feat / fix / test / chore
- 每个任务一个提交；工作区保持干净（`cfz.db`、`data/raw/`、`.superpowers/`、`node_modules/` 已忽略）
- **每次修改完成后必须同步 GitHub**：远程 `origin` = `git@github.com:go-bananas-wwj/olaiya_front.git`（master），提交后立即 `git push`，不留本地未推送提交
