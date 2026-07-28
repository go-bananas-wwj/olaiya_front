"""DINOv2 ViT-S/14 冻结特征 + 线性探针 (UnivFD 配方复现, 演示级)。

训练数据: data/raw/probe-train/{fake,real}/*.jpg
  - fake: pollinations.ai 生成图 (sana) + Wikimedia Commons Midjourney 图
  - real: picsum.photos 真实照片
各约 40 张, 提取 DINOv2 特征 (原图+水平翻转), L2 归一化后训线性头。

CLI:
    python3 data/tools/train_probe_dinov2.py                 # 训练并保存探针
    python3 data/tools/train_probe_dinov2.py --eval IMG ...  # 用已有探针评估

产出: data/models/ai-image-detector/dinov2/probe_linear.pth
"""

import argparse
import os

import torch
import torch.nn as nn
import torchvision.transforms as T
from PIL import Image

ROOT = os.path.join(os.path.dirname(__file__), "..")
DINOV2_WEIGHTS = os.path.join(ROOT, "models", "ai-image-detector", "dinov2", "dinov2_vits14_pretrain.pth")
PROBE_PATH = os.path.join(ROOT, "models", "ai-image-detector", "dinov2", "probe_linear.pth")
TRAIN_DIR = os.path.join(ROOT, "raw", "probe-train")

TRANS = T.Compose(
    [
        T.Resize(256),
        T.CenterCrop(224),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ]
)


def pick_device() -> str:
    if hasattr(torch, "npu") and torch.npu.is_available():
        return "npu:0"
    return "cpu"


def load_backbone(device: str) -> nn.Module:
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", pretrained=False)
    state = torch.load(DINOV2_WEIGHTS, map_location="cpu", weights_only=False)
    model.load_state_dict(state)
    return model.to(device).eval()


@torch.no_grad()
def extract(model: nn.Module, path: str, device: str) -> torch.Tensor:
    img = Image.open(path).convert("RGB")
    xs = [TRANS(img), TRANS(img.transpose(Image.FLIP_LEFT_RIGHT))]
    feats = model(torch.stack(xs).to(device)).mean(dim=0)  # (384,)
    return (feats / feats.norm()).cpu()


def iter_train_images():
    for kind, y in (("fake", 1), ("real", 0)):
        d = os.path.join(TRAIN_DIR, kind)
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                yield os.path.join(d, f), y


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", nargs="*", default=None, help="跳过训练, 直接评估图片")
    ap.add_argument("--device", default=pick_device())
    args = ap.parse_args()
    device = args.device

    backbone = load_backbone(device)
    probe = nn.Linear(384, 1)

    if args.eval is None:
        X, Y = [], []
        for path, y in iter_train_images():
            X.append(extract(backbone, path, device))
            Y.append(y)
        X = torch.stack(X).to(device)
        Y = torch.tensor(Y, dtype=torch.float32, device=device)
        print(f"训练样本: fake={int(Y.sum().item())}, real={int((Y == 0).sum().item())}")
        probe.to(device)
        opt = torch.optim.AdamW(probe.parameters(), lr=1e-2, weight_decay=1e-1)
        lossf = nn.BCEWithLogitsLoss()
        for _ in range(300):
            opt.zero_grad()
            loss = lossf(probe(X).squeeze(-1), Y)
            loss.backward()
            opt.step()
        acc = ((probe(X).squeeze(-1) > 0).float() == Y).float().mean().item()
        print(f"训练集 acc={acc:.4f} loss={loss.item():.4f}")
        torch.save(probe.state_dict(), PROBE_PATH)
        print("探针已保存:", PROBE_PATH)
    else:
        probe.load_state_dict(torch.load(PROBE_PATH, map_location="cpu", weights_only=False))
        probe.to(device).eval()
        with torch.no_grad():
            for path in args.eval:
                f = extract(backbone, path, device).to(device)
                prob = probe(f).sigmoid().item()
                label = "AI生成" if prob >= 0.5 else "真实"
                print(f"{path}\tprob_fake={prob:.4f}\t{label}")


if __name__ == "__main__":
    main()
