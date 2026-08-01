"""AI 生图检测 sidecar（DINOv2 ViT-S/14 冻结特征 + 线性探针，模型常驻内存）。

主 venv 无 torch，检测做成独立进程（.venv-llm 运行）；主后端经
POST /api/detect-image 代理转发到本服务。技术选型见 docs/image-detection-spike.md。

tmux 启动（仓库根目录）：
    tmux new-session -d -s cfz-vision -c /root/workspace/olaiya \\
      ".venv-llm/bin/python -m uvicorn vision_service.app:app --host 127.0.0.1 --port 8101"

权重：data/models/ai-image-detector/dinov2/（骨干 88MB + 自训线性探针 4KB）。
torch 在首次 /detect 请求时才导入并加载模型：模块本身不依赖 torch，
主 venv 可直接 import 本模块跑单测（dependency_overrides 注入假分数）。
"""

import io
import os

# torch_npu 自动加载在纯 CPU 环境会因 libstdc++ 版本报错，须在 import torch 前关掉
os.environ.setdefault("TORCH_DEVICE_BACKEND_AUTOLOAD", "0")

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DINOV2_WEIGHTS = os.path.join(ROOT, "data", "models", "ai-image-detector", "dinov2", "dinov2_vits14_pretrain.pth")
PROBE_PATH = os.path.join(ROOT, "data", "models", "ai-image-detector", "dinov2", "probe_linear.pth")

# 阈值取 0.7（留出集 6/6，见 spike 文档 §4）；<0.3 判真实，介于两者之间不确定
AI_THRESHOLD = 0.7
REAL_THRESHOLD = 0.3

_scorer = None  # 惰性单例：首次请求加载（CPU 加载骨干约数秒）


def _load_scorer():
    """加载 DINOv2 骨干 + 线性探针，返回打分函数 score(image_bytes) -> prob_fake。

    与 data/tools/train_probe_dinov2.py 同一配方：Resize256→CenterCrop224→ImageNet 归一化，
    原图 + 水平翻转 TTA，特征取均值后 L2 归一化，探针 sigmoid 即 prob_fake。
    """
    import torch
    import torch.nn as nn
    import torchvision.transforms as T
    from PIL import Image

    backbone = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", pretrained=False)
    backbone.load_state_dict(torch.load(DINOV2_WEIGHTS, map_location="cpu", weights_only=False))
    probe = nn.Linear(384, 1)
    probe.load_state_dict(torch.load(PROBE_PATH, map_location="cpu", weights_only=False))
    backbone.eval()
    probe.eval()
    trans = T.Compose(
        [
            T.Resize(256),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )

    @torch.no_grad()
    def score(image_bytes: bytes) -> float:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        xs = torch.stack([trans(img), trans(img.transpose(Image.FLIP_LEFT_RIGHT))])
        feats = backbone(xs).mean(dim=0)
        feats = feats / feats.norm()
        return probe(feats).sigmoid().item()

    return score


def get_scorer():
    """FastAPI 依赖：返回打分函数（测试可 override 注入假分数，不触真模型）。"""
    global _scorer
    if _scorer is None:
        _scorer = _load_scorer()
    return _scorer


def verdict_for(score: float) -> str:
    if score > AI_THRESHOLD:
        return "ai"
    if score < REAL_THRESHOLD:
        return "real"
    return "uncertain"


app = FastAPI(title="成分真言 视觉检测 sidecar", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _scorer is not None}


@app.post("/detect")
def detect(file: UploadFile = File(...), scorer=Depends(get_scorer)):
    """multipart 图片上传 → prob_fake 分数与三档判定。分数为模型估计值，仅供演示。"""
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        score = float(scorer(content))
    except Exception:
        raise HTTPException(status_code=400, detail="图片无法解码或格式不支持")
    return {
        "score": round(score, 4),
        "verdict": verdict_for(score),
        "threshold": AI_THRESHOLD,
        "note": "检测为模型估计，仅供演示",
    }
