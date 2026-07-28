# NPU 推理环境搭建记录（vLLM-Ascend on Atlas 800I A2 / 910B4-1）

> 日期：2026-07-28 ｜ 结论：**Qwen2.5-0.5B-Instruct 已在单卡 NPU 上跑通 vLLM 离线推理**
> 独立 venv：`.venv-llm/`（与测试用 `.venv` 完全隔离）

## 硬件 / 系统

- 8×910B4-1（64GB HBM/卡），驱动 26.0.rc1，`npu-smi` 可用
- openEuler 24.03 aarch64，Python 3.11.15（来自 conda env `/data/wwj_torch21/conda/envs/torch26`）
- CANN **9.0.0**（`/usr/local/Ascend/ascend-toolkit/set_env.sh`），NNAL 已装（`/usr/local/Ascend/nnal/atb/set_env.sh`）

## 最终可用版本组合

| 组件 | 版本 | 来源 |
|---|---|---|
| CANN | 9.0.0 | 系统预装 |
| vllm | 0.22.1 | PyPI（清华镜像），`--no-deps` 安装 |
| vllm-ascend | 0.22.1rc1 | 华为云 variant 源，`--no-deps` 安装 |
| torch | 2.10.0+cpu | 华为云 variant 源（精简 aarch64 wheel，146MB） |
| torch-npu | 2.10.0 | 华为云 variant 源 |
| triton-ascend | 3.2.1 | 华为云 **plain** 源（variant 源只有 3.2.0） |
| torchvision / torchaudio | 0.25.0 / 2.10.0 | PyPI，`--no-deps`（vllm 运行时需要 import torchvision） |
| numba | 0.65.0 | PyPI（vllm EngineCore 硬依赖） |

版本矩阵依据：[vllm-ascend versioning policy](https://docs.vllm.ai/projects/ascend/en/latest/community/versioning_policy.html) —— v0.22.1rc1 对应 vLLM 0.22.1 + CANN 9.0.0 + torch/torch_npu 2.10.0，与本机 CANN 9.0.0 精确匹配（最新 v0.23.0rc1 要求 CANN 9.0.1，不可用）。

**注意**：vllm 0.22.1 的 metadata 硬钉 `torch==2.11.0`，vllm-ascend 0.22.1rc1 钉 `torch==2.10.0`，二者冲突。解法是两者都用 `pip install --no-deps` 安装后手动补齐依赖（`pip check` 会报 vllm 的 torch 版本不满，属预期，运行时实测正常）。

## 环境变量（每次使用必配）

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /usr/local/Ascend/nnal/atb/set_env.sh
# conda libstdc++ 优先（系统 /lib64 的 CXXABI_1.3.15 太旧，torch_npu import 会炸）
export LD_LIBRARY_PATH=/data/wwj_torch21/conda/envs/torch26/lib:$LD_LIBRARY_PATH
# 选卡
export ASCEND_RT_VISIBLE_DEVICES=4        # 按需
# 必须 spawn！fork 模式下 EngineCore 子进程 dlopen vllm_ascend_C.so 会 100% CPU 自旋（见踩坑 4）
export VLLM_WORKER_MULTIPROC_METHOD=spawn
```

## 启动命令

### 离线推理（已验证）

```bash
.venv-llm/bin/python data/tools/npu_smoke_test.py data/models/llm/Qwen2.5-0.5B-Instruct 1
# 输出末尾打印 SMOKE_TEST_OK 即成功（脚本含 if __name__ == "__main__" 保护，spawn 必需）
```

### OpenAI API server（未实测，供参考）

```bash
.venv-llm/bin/vllm serve data/models/llm/Qwen2.5-14B-Instruct \
    --tensor-parallel-size 2 --enforce-eager --port 8008
```

## 踩坑与解法（按时间序）

1. **系统级 clash 代理（127.0.0.1:7891，写在 /etc/environment）劫持全部流量**，清华镜像/modelscope 单连接掉到 ~10KB/s，pip 反复 IncompleteRead。解法：所有 pip/curl 用 `env -u http_proxy -u https_proxy ...` 或 `curl --noproxy '*'` 绕过；大文件用 16 并发 HTTP Range 分段下载（脚本 `data/tools/ms_fast_download.sh`），聚合 ~1MB/s。
2. **PyPI aarch64 的 torch 2.11.0 依赖整个 CUDA 13 软件栈**（cuda-toolkit/cudnn/nccl/nvshmem/triton 等，数 GB），NPU 场景完全无用。解法：vllm/vllm-ascend 一律 `--no-deps` 安装，torch 用华为云 variant 源的 2.10.0+cpu 精简 wheel，CUDA 依赖全跳过。
3. **torch_npu import 报 `CXXABI_1.3.15 not found`**：venv 基于 conda python，conda 的 libicui18n 需要新版 libstdc++，而 CANN set_env.sh 把系统 /lib64 提前。解法：`LD_LIBRARY_PATH` 里前置 conda 的 lib 目录。
4. **fork 模式 EngineCore 卡死（最隐蔽的坑）**：默认 fork 下，EngineCore 子进程 import `vllm_ascend_C`（dlopen）时 99.9% CPU 自旋 ≥30 分钟，py-spy 栈停在 `create_module`（camem.py:58）；同一 .so 在干净进程里 7.8s 即加载完——fork 后 dlopen 与已初始化的 CANN 运行时锁状态冲突。解法：`VLLM_WORKER_MULTIPROC_METHOD=spawn`（且入口脚本必须有 `__main__` 保护）。
5. spawn 后暴露的两个缺包：`numba`（EngineCore 硬依赖）、`torchvision`（vllm worker import 需要，torch 2.10 配 torchvision 0.25.0）。
6. pip 的 dependency resolver 对「已安装但 --no-deps 的 vllm」仍会拉 torch==2.11.0 及其 CUDA 树——所以后续补包都要显式指定包名，别再直接 `pip install vllm==0.22.1`。

## 验证记录

- 2026-07-28 22:50，device 4（ASCEND_RT_VISIBLE_DEVICES=4，spawn，enforce_eager）：
  - `用一句话解释什么是化妆品功效宣称：` → 通顺中文续写 ✓
  - `The capital of France is` → 英文续写 ✓
  - 日志末尾 `SMOKE_TEST_OK`，进程正常退出，显存已释放
- Qwen2.5-14B-Instruct（TP=2，0/1 卡）**未验证**：权重下载仅 ~1.2G/30G（7/8 分片 incomplete），且 14B 的下载进程与其他任务共享 ~1MB/s 带宽，预计还需数小时。

## 遗留风险

- vllm metadata 的 torch==2.11.0 与实际 torch 2.10.0 不一致：目前 0.5B eager 模式正常，但 graph 模式（非 enforce_eager）和多模态路径未测；14B TP=2 是下一个验证点。
- triton-ascend 3.2.1 与 vllm 的 triton kernel 导入不匹配（启动时 `No module named 'triton.language.target_info'` 警告），eager 模式无影响，编译模式可能受限。
- 慢磁盘（~1MB/s 写）：大模型权重加载会比较慢，建议预热页缓存。
- NPU 0 有外部进程残留（pid 4170061, 216MB），用卡前先看 `npu-smi info`。
