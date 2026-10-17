# SkinSort 参考设计验收（2026-10-17）

final result: passed

## 对照依据

用户提供的 SkinSort 六张截图为视觉依据，核心采用产品概览、功效与贡献成分、并排成分表和更多对比四种结构。原站受 Cloudflare 限制，采用用户截图，不绕过访问限制。不是复制 SkinSort 的评分或数据库。

- 概览原图：`codex-clipboard-3c0121e7-0171-49fe-be51-157e937b8653.png`，834 × 827。
- 成分表原图：`codex-clipboard-ec84d5ca-6651-4682-a539-b3ce7af9649f.png`，557 × 761；局部对照使用上部 485px。
- 实现：`http://127.0.0.1:5175`，834 × 1000、1280 × 800、390 × 844 CSS px，deviceScaleFactor=1。
- 对照图将原图和真实页面捕获并排，概览裁去颜鉴自有页眉 74px，成分表按同宽缩放。产品、语言和资料内容不同，不作像素误差百分比宣称。

## 第一轮发现

- P2：834px 下概览的图片区和资料清单留白过多，延后功效入口。收紧桌面图片区，资料数量与标签同行，手机仍可换行。调整后重新捕获并对照。
- 已确认：产品图使用精确匹配成分来源页面的真实图，不生成包装；中文名称、规格与价格仍来自原接口。未有匹配图片的全库产品明确提示暂未收录。

## 有意保留的内容差异

- 以真实收录情况替代参考截图中的安全标签；不补造评价、评分、商业购买链接、肤感或功效承诺。
- 八方向采用原有 `evidence-index-v1`，两产品共用刻度；先显示四方向，可展开全部。成分权重、原文、限制与浓度资料保留。
- 参考图的紫色用于共享成分；绿色图标用于资料或功效类别识别，不能解释为安全或疗效认证。
- 成分两侧按各自已知来源位次排列，不为对齐而伪造配方顺序；未知位次明确说明。

## 设计研究

- [Baymard：4 Ways to Optimize Comparison Feature for Scanning](https://baymard.com/research-articles/user-friendly-comparison-tools)：分组、差异过滤、持续可见的对照对象和行分隔。
- [NN/g：Mobile Tables](https://www.nngroup.com/articles/mobile-tables/)：移动端保留对象上下文；本页使用两列有界列表，避免整个页面横向溢出。
- [SkinSort：Product comparison tool](https://skinsort.com/support/what-is-the-product-comparison-tool)：并排逐项比较的使用方式。


## 修复后复验

已收紧桌面图片高度和资料清单行高，重新生成同一 834px 视窗及成分区的并排对照，再次查看后无待修 P0/P1/P2。保留来源解释所需文本，未复制参考产品的不同内容。1280 × 800 下功效区标题位于约 734px；390px 页面宽度为 390px，没有横向溢出。

- [同视窗概览并排对照](docs/design/overview-reference-comparison.png)
- [成分表局部并排对照](docs/design/ingredients-reference-comparison.png)
- [834px 完整实现](docs/design/comparison-desktop.png)
- [390px 完整实现](docs/design/comparison-mobile.png)

实际浏览器检查了图片比例、分隔线、名称和价格对齐、滚动身份、目录定位、共享高亮、只看差异、紧凑视图、全部成分展开、功效联动与来源抽屉。展示版 10 项浏览器测试、原站 12 项浏览器回归、7 项逻辑测试通过。原站与展示版分别完成生产构建。

后续细节：更多产品参考图可继续按精确来源补充；本轮只有四款演示产品有图片。当前缺失用途资料如实显示，不使用推断文案填充版面。

全量后端回归：817 通过、1 跳过；本轮没有后端或数据结构变更。四张产品图的 SHA-256 与记录一致。
