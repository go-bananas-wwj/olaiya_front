"""NPU vLLM 链路冒烟测试：离线推理一次生成。

用法：
    source /usr/local/Ascend/ascend-toolkit/set_env.sh
    source /usr/local/Ascend/nnal/atb/set_env.sh
    export LD_LIBRARY_PATH=/data/wwj_torch21/conda/envs/torch26/lib:$LD_LIBRARY_PATH
    ASCEND_RT_VISIBLE_DEVICES=0 VLLM_WORKER_MULTIPROC_METHOD=spawn \
        .venv-llm/bin/python data/tools/npu_smoke_test.py [模型路径] [tp]
"""
import sys


def main():
    from vllm import LLM, SamplingParams

    model = sys.argv[1] if len(sys.argv) > 1 else "data/models/llm/Qwen2.5-0.5B-Instruct"
    tp = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    prompts = [
        "用一句话解释什么是化妆品功效宣称：",
        "The capital of France is",
    ]

    sampling_params = SamplingParams(temperature=0.8, top_p=0.95, max_tokens=64)
    llm = LLM(model=model, tensor_parallel_size=tp, enforce_eager=True)
    outputs = llm.generate(prompts, sampling_params)
    for output in outputs:
        print(f"Prompt: {output.prompt!r}\nGenerated: {output.outputs[0].text!r}\n")
    print("SMOKE_TEST_OK")


if __name__ == "__main__":
    main()
