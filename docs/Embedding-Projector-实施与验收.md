# Google Embedding Projector 参考复刻：实施与验收

日期：2026-10-19（北京时间）。用户已明确选定 [Google Embedding Projector](https://projector.tensorflow.org/)，包括点击一点之后的联动效果。本轮替代此前地图／群岛／图片图谱方向。

## 参考事实与实现范围

已实际操作参考站，捕获1440×1000、deviceScaleFactor=1的默认、选中、隔离，以及390×844手机状态。源站选中一点后：背景降灰，选中点与名称突出，近邻金橙，画布右上浮动元资料，右侧原空间距离表；隔离仅保留选中及近邻。源码来源为TensorBoard Projector（Apache 2.0）；颜鉴独立实现界面与交互，保留自己的品牌和数据。

本轮保留三栏、60px酒红顶栏、Roboto、白底点云、平直工具区及紧凑列表。源站固定宽侧栏在手机挤出画布，本版采用抽屉。产品名称比英语词长，采用短显、完整title/aria、标签避让与必要leader线。没有清楚位置时省略该文字，真实点和右侧身份仍保留；不抖动或挪动产品坐标。

已实现：UMAP/PCA、三维旋转／二维平移、滚轮缩放、Home、聚焦、真实点选、重叠列表、标签内容／显示与颜色、点大小、全库搜索、5—100近邻、两种原空间距离、隔离／显示全部／清除、浮动产品资料、成分与证据抽屉，以及独立任意两款八维对比。

不提供未实现的t-SNE/自定义拟合按钮；固定成分输入不开放上传或公开发布数据。投影参数来自资源元数据，主流程不调用生成模型。旧指纹、排行榜与圆桌口径保持兼容。

## 真实数据与算法

- 数据库固定快照：`0fd2e820413ccc64b1ca7c6207b7cc1ceb8dadef`，3749款／23品牌、113945产品成分关联、2396断言、322来源。
- v2输入为同快照4096维归一化Faiss向量，源index SHA：`1bfa3201e58d36c4c275389e0418dab86627fcff5c65b98be4a1314ebba928da`。
- 独立新产物 `ingredient-projector-v2`：735143字节。原二维3749对x/y逐值复制冻结v1；UMAP3D直接从原始向量拟合，PCA使用原向量中心化full SVD，未用二维补Z。
- 3714个唯一原向量；35个重复观测在各新空间均保持同坐标。新进程独立重建两次字节完全一致。

| 空间 | 原始10近邻平均保留率 | 抽样trustworthiness |
|---|---:|---:|
| 冻结UMAP二维 | 44.1371% | 0.964307 |
| 真实UMAP三维 | 49.5332% | 0.972828 |
| PCA前三主成分 | 11.0830% | 0.805761 |

PCA三轴解释方差7.2911%、4.7199%、3.4608%，合计15.4718%；二维显示所选两轴之和，不误用三维近邻指标。所有指标是投影质量，非产品功效准确率。

新增字段：每款 `coordinates_3d`、`pca_coordinates`；顶层三维计数及分空间元数据。原 `coordinates`、二维method、证据数值与既有接口保留。旧v1三维为不可用；异常某个新空间仅降级对应模式，未知不补坐标。

近邻接口原默认5不变，上限50扩100，新增101产品真实Faiss回归验证。默认100条由原始索引召回；余弦距离为1−score，归一化欧氏距离为√(2−2score)。切投影、轴、旋转、隔离或距离显示不重定义排名；独立按源向量计算最大误差约1.5e-6。

## 资源发布

- 私有数据集：`WeijieWu/yanjian-showcase-data`。
- 三维布局独立固定提交：`ea284a4798743d3c11780983df3c24c95247e9aa`，文件名仍为 `product-space-layout.json`。
- 布局SHA：`e209bbcd009a527c1b6bd85f1c314abc04a59919519a2ea56fd1b31db4e644f4`；上传后已重新下载核验。
- 只切换布局revision/SHA；数据库仍为原0fd快照，原二维资源与坐标不改写。启动写入 `/mnt/workspace/cfz/layouts/<revision>/`，校验后复用，不覆盖原数据库。
- 现有私有 `WeijieWu/yanjian-ingredient-compare`、免费 `platform/2v-cpu-8g-mem` 保持；运行时无UMAP/Numba/torch，仅读取坐标。
- Three.js 0.180.0、Roboto 5.3.0固定版本，自托管字体及MIT/OFL许可；无热链Google字体、图标或示例数据。

## 失败测试与审核迭代

| 阶段 | 发现与修复 | 复验 |
|---|---|---|
| 数据服务 | 先补v2资格/缺坐标/模式坏损/冻结源守卫失败测试，再实现；保留v1与二维值 | 独立数学审核通过 |
| 原空间距离 | PCA二维误显示PCA三维11.1% → 先失败逻辑测试，二维隐藏该质量指标，仅显示真实所选轴解释方差 | 独立浏览器与向量复算通过 |
| 首次真实主UI | StrictMode模拟卸载导致同canvas context过早丢失 → 仅未复用canvas异步丢context | 主UI ready与真3D点击通过 |
| 第一轮视觉 | 10近邻橙色反馈弱 → 默认100个真实近邻；长名称重叠 → 14/12px、避让、短显、leader | 第二轮视觉 **8.7/10通过** |
| 相机与手机 | bbox球和硬半径导致紧密6点仅20px → 真视锥fit与局部GPU原点；全库与子集限制维度占约80%，不拉伸XYZ | 独立UX：390手机312×145px，6点全可见 |
| resize绘制 | 连续resize后存在短暂清缓冲空帧 → RO同步paint并保留按需buffer；局部隐藏全库巨轴 | 0/200ms canvas像素一致；像素浏览器回归通过 |
| 最终新发布专家 | 只读审状态、URL、旧响应、未知资料、许可与Docker白名单 | 无P0/P1/P2，可进入云端实测 |

视觉评分是专家判断，不是用户满意度测量。独立数据／UX／工程／视觉结论分别基于向量、真实操作、像素和参考截图，不能互相替代。

## 本地验证

全量pytest **862通过、1跳过**；前端逻辑 **32通过**；展示与对比浏览器 **25通过**（含StrictMode、真实像素和WebGL失去后重试）；原站12项浏览器在默认构建后通过。原站与展示版生产构建通过，默认 `web/` 按项目要求提交。

覆盖：原坐标不变、同向量同坐标、缺失三维、原空间100近邻、实际点选、3D旋转／二维平移、PCA轴、原空间两种距离、隔离恢复、紧密近邻、真实灰点像素、重复投影可达、旧请求迟到、任意A/B往返、两个真实案例、成分来源、未知浓度／价格／单位、390/834布局、WebGL错误恢复。没有模型推理要求。

云端实际HTML/API、生产构建哈希、资源版本、匿名401及重新部署后的数据恢复须在发布后单独核验，不能从本地测试推定。私有云浏览器通过仅向本空间域名附加授权的HTTP转发读取真实响应完成，不伪造API；不等于已核验账号登录后的平台外层页面。

## 视觉证据

- [参考默认](design/projector-source-default.png)、[参考选中](design/projector-source-desktop-selected.png)、[参考隔离](design/projector-source-desktop-isolated.png)、[参考手机固定侧栏](design/projector-source-mobile-selected.png)。
- [同输入默认并排](design/projector-comparison-default.png)、[同输入选中并排](design/projector-comparison-selected.png)。两侧1440×1000、1x；源为10000条200维词向量PCA，颜鉴为3749款4096维产品UMAP，数据／投影不同，不作点云形状像素一致性结论。
- [桌面默认](design/projector-desktop-default.png)、[选中100近邻](design/projector-desktop-selected.png)、[隔离101款](design/projector-desktop-isolated.png)、[1280桌面](design/projector-desktop-1280.png)。
- [手机点云](design/projector-mobile-selected.png)、[手机列表](design/projector-mobile-neighbors.png)、[紧密6点](design/projector-mobile-tight-neighbors.png)。
- [两款对比](design/projector-two-products.png)、[手机对比](design/projector-two-products-mobile.png)。
