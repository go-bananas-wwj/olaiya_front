"""AI 生图检测（CNNDet: Wang et al. CVPR 2020, ResNet-50 Blur+JPEG(0.5)）。

CLI:
    python3 data/tools/detect_ai_image_cnndet.py IMG [IMG ...]

权重:
    data/models/ai-image-detector/cnndet/blur_jpg_prob0.5.pth
    (官方 https://github.com/PeterWang512/CNNDetection, dropbox 直链)

预处理与官方 demo.py 一致: ToTensor + ImageNet 归一化, 不裁剪;
仅把长边 >1024 的图等比缩小以控制推理耗时。输出 prob_fake >=0.5 判为 AI 生成。
"""

import argparse
import os

import torch
import torchvision.transforms as T
from PIL import Image
from torchvision.models import resnet50

WEIGHTS = os.path.join(
    os.path.dirname(__file__), "..", "models", "ai-image-detector", "cnndet", "blur_jpg_prob0.5.pth"
)

TRANS = T.Compose(
    [
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ]
)


def pick_device() -> str:
    if hasattr(torch, "npu") and torch.npu.is_available():
        return "npu:0"
    return "cpu"


def load_image(path: str) -> torch.Tensor:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > 1024:  # 仅等比缩小，不改纵横比
        s = 1024 / max(w, h)
        img = img.resize((round(w * s), round(h * s)), Image.BILINEAR)
    return TRANS(img)


def main() -> None:
    ap = argparse.ArgumentParser(description="CNNDet AI 生图检测")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--device", default=pick_device())
    args = ap.parse_args()

    model = resnet50(num_classes=1)
    state = torch.load(WEIGHTS, map_location="cpu")
    model.load_state_dict(state["model"])
    model.to(args.device).eval()

    with torch.no_grad():
        for path in args.images:
            x = load_image(path).unsqueeze(0).to(args.device)
            prob = model(x).sigmoid().item()
            label = "AI生成" if prob >= 0.5 else "真实"
            print(f"{path}\tprob_fake={prob:.4f}\t{label}")


if __name__ == "__main__":
    main()
