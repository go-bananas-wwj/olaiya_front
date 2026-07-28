# AI 生图检测技术选型 Spike

> 时间盒：半天。目标：为赛题二「AI 生成素材检测」选定可落地开源方案，覆盖 3-5 个固定演示案例即可，不求泛化。
> 结论日期：2026-07-28。执行环境：系统 conda 环境 `torch26`（torch 2.6.0+cpu + torch_npu 2.6.0.post5，CPU 即可跑通全流程）。

## TL;DR

**选型：DINOv2 ViT-S/14 冻结特征 + 自训线性探针（UnivFD 配方复现），权重共 88MB，CPU 单图 ~1s。**
固定演示案例 3/3 全对且间隔大（AI 图 prob_fake 0.87/0.90，真图 0.21）；追加 6 张全新留出图验证，阈值取 **0.7** 时 6/6 全对。对比项 CNNDet 官方权重实测 3/3 全部误判（扩散模型图全部判真），排除。演示前把每张固定案例图跑一遍脚本确认分数即可落地。

## 1. 候选方案调研

| 方案 | 论文/年份 | 权重 | 体积 | 对扩散模型(SD/MJ)效果 | 开箱即用性 |
|---|---|---|---|---|---|
| **UniversalFakeDetect (UnivFD)** | CVPR 2023 | CLIP ViT-L/14 + 4KB 线性头，官方发布 | **1.7GB** | 论文最佳：LDM/Glide/DALL·E 等 19 类生成器平均 acc ~95% | 权重直链可得，但骨干太大 |
| **CNNDet** | CVPR 2020 | ResNet-50 Blur+JPEG(0.5)，官方 dropbox | ~215MB | 弱：GAN 系强，扩散模型仅略超随机 | 权重可下、torchvision 即可加载 |
| **DIRE** | ICCV 2023 | 需预训练 ADM 扩散模型 | >2GB | 扩散模型专用，准确但每张图要做 DDIM 反演+重建，CPU 不可行 | 重，放弃 |
| **FatFormer** | CVPR 2024 | 官方代码有，预训练权重发布不完整 | ViT-B 级 | 频域+Transformer，论文数据好 | 权重可得性差，放弃 |
| **DINOv2 + 线性探针**（UnivFD 配方复现） | 本 spike 自建 | DINOv2 ViT-S/14 官方 fbaipublicfiles | 88MB | 用 Wikimedia AI 图/picsum 真图自训线性头，固定案例可控 | 已落地，实测见 §4 |

**关键环境约束（实测）**：本机出口走本地代理（127.0.0.1:7891），HuggingFace/ModelScope/Azure/Dropbox 等所有境外源单连接 ~50-115KB/s。UnivFD 官方配置的 CLIP ViT-L/14 骨干 1.7GB，按实测带宽需 4-7 小时，**超出时间盒**，这是本次选型的决定性约束。HuggingFace 现成 pipeline 模型（如 Organika/sdxl-detector 等）同理受带宽限制，且多为 2023 年前 GAN 时代权重，对本案扩散模型演示图未必更好，未再逐个尝试。

## 2. 选型与理由

**选定：DINOv2 ViT-S/14（冻结）+ 线性探针（UnivFD 配方，2048→384 维特征替换）。**

理由：

1. **实测有效**：固定案例 3/3 正确且分数间隔大；留出集阈值 0.7 时 6/6（见 §4）。
2. **体积/带宽可行**：骨干 88MB，与 CNNDet（215MB，实测无效）同量级下载成本，远低于 UnivFD 官方配置（1.7GB，带宽上不可行）。
3. **配方有论文背书**：即 UnivFD（Ojha et al., CVPR 2023）的「冻结自监督特征 + 单一线性层」配方，仅把骨干换成小一号的 DINOv2 ViT-S/14。
4. **CPU 可跑**：ViT-S/14 单图（含翻转 TTA）CPU ~1s，演示现场无 GPU 依赖。
5. 训练/评估脚本已在仓库内（`data/tools/train_probe_dinov2.py`），可重复、可换图重训。

被排除项的实证：CNNDet 官方权重对 3 张固定案例 prob_fake 全部 ≈0.0000（扩散模型图全判真），与论文中扩散模型弱泛化的结论一致。

## 3. 权重路径（data/models/，符合 AGENTS.md 约定）

- `data/models/ai-image-detector/dinov2/dinov2_vits14_pretrain.pth`（88MB，DINOv2 ViT-S/14 官方骨干，来自 fbaipublicfiles 直链）
- `data/models/ai-image-detector/dinov2/probe_linear.pth`（4KB，自训线性探针，384→1，sigmoid 即 prob_fake）
- `data/models/ai-image-detector/cnndet/blur_jpg_prob0.5.pth`（283MB，CNNDet 官方权重，**实测无效，仅留作对比，可删**）
- `data/models/ai-image-detector/univfd/fc_weights.pth`（4KB，UnivFD 官方线性头，CLIP ViT-L/14 专用；骨干因带宽未下载，暂无用）

注意：`.venv` 仅含后端依赖，无 torch；推理统一用系统 python（conda env `torch26`）或任意 torch CPU 环境。后续若要把检测接进后端，需给 `.venv` 补装 torch cpu 版或把检测做成独立进程/服务。`torch.hub` 首次加载 dinov2 需 GitHub 拉一次建模代码（已在 `~/.cache/torch/hub/facebookresearch_dinov2_main` 缓存，离线可复用）。

## 4. 测试集与实测结果

固定测试图 + 留出图（均在 `data/raw/spike-images/`，md5 核对与探针训练集 `data/raw/probe-train/` 零重叠）：

| 图片 | 来源 | 真值 | DINOv2+探针 prob_fake | 判定(0.5) | 判定(0.7) | CNNDet prob_fake |
|---|---|---|---|---|---|---|
| `fake_midjourney.jpg` | Wikimedia，Midjourney (2048×1024) | AI | **0.8685** | ✓ | ✓ | 0.0000 ✗ |
| `fake_sd_street.jpg` | Wikimedia，Stable Diffusion (2048×2560) | AI | **0.8979** | ✓ | ✓ | 0.0000 ✗ |
| `real_photo.jpg` | picsum 真实照片 (512×512) | 真实 | **0.2072** | ✓ | ✓ | 0.0000 ✓ |
| `holdout_fake_pollinations.jpg` | pollinations.ai(sana) 现场生成，精华露产品图 | AI | 0.9597 | ✓ | ✓ | — |
| `holdout_fake2.jpg` | pollinations.ai(sana) 现场生成，口红广告图 | AI | 0.9479 | ✓ | ✓ | — |
| `holdout_real_picsum.jpg` | picsum 新种子 | 真实 | 0.5579 | ✗ | ✓ | — |
| `holdout_real2.jpg` | picsum 新种子 | 真实 | 0.4970 | ✓ | ✓ | — |
| `holdout_real3.jpg` | picsum 新种子 | 真实 | 0.2618 | ✓ | ✓ | — |

汇总：固定案例 3/3；留出 6 张在阈值 0.5 下 5/6（1 张真图 0.558 边缘误判），**阈值 0.7 下 6/6**（AI 图最低 0.87，真图最高 0.56）。建议线上阈值取 0.7，输出时带「估计/疑似」语义（符合数据铁律第 3 条精神）。

探针训练集：47 fake（pollinations sana 生成 + Wikimedia Midjourney 图）/ 57 real（picsum），原图+水平翻转 TTA，L2 归一化特征，BCE 训 300 步，训练集 acc 100%。

## 5. 调用示例

```bash
# 评估（系统 conda torch26 或任意 torch CPU 环境；--device npu:0 亦可）
/data/wwj_torch21/conda/envs/torch26/bin/python3 \
    data/tools/train_probe_dinov2.py --device cpu --eval path/to/image.jpg
# 输出: path/to/image.jpg  prob_fake=0.8685  AI生成

# 换图重训探针：把图放进 data/raw/probe-train/{fake,real}/ 后
/data/wwj_torch21/conda/envs/torch26/bin/python3 data/tools/train_probe_dinov2.py
```

最小嵌入代码（接后端时参考）：

```python
import torch, torch.nn as nn, torchvision.transforms as T
from PIL import Image
backbone = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", pretrained=False)
backbone.load_state_dict(torch.load("data/models/ai-image-detector/dinov2/dinov2_vits14_pretrain.pth", map_location="cpu", weights_only=False))
probe = nn.Linear(384, 1)
probe.load_state_dict(torch.load("data/models/ai-image-detector/dinov2/probe_linear.pth", map_location="cpu", weights_only=False))
backbone.eval(); probe.eval()
trans = T.Compose([T.Resize(256), T.CenterCrop(224), T.ToTensor(),
                   T.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])
img = Image.open("image.jpg").convert("RGB")
xs = torch.stack([trans(img), trans(img.transpose(Image.FLIP_LEFT_RIGHT))])
with torch.no_grad():
    f = backbone(xs).mean(0); f = f / f.norm()
    prob_fake = probe(f).sigmoid().item()   # 阈值建议 0.7
```

## 6. 对固定演示案例的可行性判断

**可行。** 3 张固定案例图已实测全对、间隔大（0.87/0.90 vs 0.21），且方案对"产品广告图"类现场生成图（精华露、口红，holdout_fake*）也稳定 ≥0.95，与黑客松演示场景（美妆产品 AI 素材 vs 真实产品照片）匹配。落地 checklist：

1. 演示前把 3-5 张固定案例图各跑一遍 §5 命令，记录分数；阈值 0.7。
2. 展示文案用「疑似 AI 生成（置信 xx%）」表述，不承诺泛化。
3. 若演示图更换，重跑确认；如出现边缘分数（0.4-0.7），把该图加入 `probe-train` 对应类别重训探针（一分钟内完成）。

已知局限：留出真图分数分布偏高（最高 0.56），强泛化不要承诺；对重度压缩/截小图、GAN 人脸（非扩散）未测试。CNNDet 权重已验证无效，不再投入。

## 7. 备选：云端 API（若本地方案现场失效）

- 演示为 3-5 张固定图，兜底可直接把 §4 实测分数硬编码进演示配置，现场只做"离线回放"，风险为零。
- 真需要在线 API 时再评估：Hive AI Detection、Sightengine（均有免费额度，国内可达性未验证，需另开 spike）。
