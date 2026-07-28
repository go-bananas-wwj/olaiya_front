"""AI 生图检测（UniversalFakeDetect: CLIP ViT-L/14 + 线性头）。

CLI:
    HF_HOME=data/models/hf_cache python3 data/tools/detect_ai_image.py IMG [IMG ...]

权重:
    - 线性头: data/models/ai-image-detector/univfd/fc_weights.pth
      (https://github.com/WisconsinAIVision/UniversalFakeDetect)
    - CLIP ViT-L/14: openai/clip-vit-large-patch14, 经 HF_HOME 缓存到 data/models/

输出: 每张图一行 `prob_fake`，>=0.5 判为 AI 生成。
依赖系统 conda 环境 torch26 (torch 2.6 + torch_npu + transformers)，自动优先用 NPU、退回 CPU。
"""

import argparse
import os

import torch
import torch.nn as nn
from PIL import Image
from transformers import CLIPImageProcessor, CLIPModel

FC_WEIGHTS = os.path.join(
    os.path.dirname(__file__), "..", "models", "ai-image-detector", "univfd", "fc_weights.pth"
)
# CLIP ViT-L/14 本地目录（从 ModelScope AI-ModelScope/clip-vit-large-patch14 下载）
CLIP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "models", "hf_cache", "clip-vit-large-patch14"
)


def pick_device() -> str:
    if hasattr(torch, "npu") and torch.npu.is_available():
        return "npu:0"
    return "cpu"


class UnivFD(nn.Module):
    """CLIP 图像特征 + 线性分类头（复刻官方 validate.py，特征先 L2 归一化）。"""

    def __init__(self, device: str):
        super().__init__()
        clip = CLIPModel.from_pretrained(CLIP_NAME)
        self.vision = clip.vision_model
        self.proj = clip.visual_projection
        state = torch.load(FC_WEIGHTS, map_location="cpu")
        self.fc = nn.Linear(768, 1)
        self.fc.load_state_dict(state)
        self.to(device).eval()
        self.processor = CLIPProcessor.from_pretrained(CLIP_NAME)

    @torch.no_grad()
    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        feats = self.proj(self.vision(pixel_values).pooler_output)  # (B, 768)
        feats = feats / feats.norm(dim=-1, keepdim=True)  # 与官方 clip.encode_image 一致
        return torch.sigmoid(self.fc(feats)).squeeze(-1)  # prob_fake


def main() -> None:
    ap = argparse.ArgumentParser(description="UniversalFakeDetect AI 生图检测")
    ap.add_argument("images", nargs="+", help="待检测图片路径")
    ap.add_argument("--device", default=pick_device())
    args = ap.parse_args()

    model = UnivFD(args.device)
    for path in args.images:
        img = Image.open(path).convert("RGB")
        inputs = model.processor(images=img, return_tensors="pt").to(args.device)
        prob = model(inputs["pixel_values"]).item()
        label = "AI生成" if prob >= 0.5 else "真实"
        print(f"{path}\tprob_fake={prob:.4f}\t{label}")


if __name__ == "__main__":
    main()
