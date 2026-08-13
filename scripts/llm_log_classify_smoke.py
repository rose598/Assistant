"""真实 qwen 日志分类冒烟脚本（第 4 周周一，LLM 辅助分类实测用）。

验证 ``DualLogClassifier`` 在**真实 LLM** 下：
- 规则可判样本 → 走规则通道（不调 LLM），结果正确；
- 规则盲区样本 → 走 LLM 兜底，qwen 是否按受控 JSON 输出合法 subtype；
- 总体覆盖率（规则 ∪ LLM 命中）/ 样本数。

用法（项目根目录，已激活 venv；**key 只进环境变量，不入聊天/不落盘**）::

    set AGENT_LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
    set AGENT_LLM_API_KEY=<你的真实 key>
    set AGENT_LLM_MODEL=qwen-chat
    python scripts/llm_log_classify_smoke.py

未配置 key 时优雅提示，走 mock 说明切换方式，不崩溃。
"""

from __future__ import annotations

import asyncio

from src.config import Config, reset_config
from src.llm.mock_llm import create_llm_client
from src.log_analysis.commands import JobRecord
from src.log_analysis.llm_log_classifier import DualLogClassifier, LLMLogClassifier

# (reason, job_state, exit_code, 预期类别说明)
SAMPLES: list[tuple[str, str, str, str]] = [
    # ---- 规则可判（应走规则、0 次 LLM 调用）----
    ("CUDA out of memory during training", "F", "137:0", "期望 gpu_oom(规则)"),
    ("conda: command not found", "F", "127:0", "期望 conda_missing(规则)"),
    ("sbatch: error: No such file or directory", "F", "1:0", "期望 path_error(规则)"),
    # ---- 规则盲区（应走 LLM 兜底，重点验证真实 qwen）----
    ("RuntimeError: NCCL timeout waiting for the barrier rank", "F", "1:0", "规则盲区→期望 LLM 判(如 env/dependency)"),
    ("Torch not compiled with CUDA enabled, can't use GPU", "F", "1:0", "规则盲区→期望 LLM 判(如 cuda_mismatch/env)"),
    ("File '/home/x/data/x' has size 0, maybe truncated download", "F", "1:0", "规则盲区→期望 LLM 判(如 path_error)"),
]


def _rec(reason: str, state: str, exit_code: str) -> JobRecord:
    return JobRecord(
        job_id="smoke", job_name="test_script", job_state=state,
        exit_code=exit_code, reason=reason, partition="Students", qos="qos_stu_default",
    )


async def main() -> int:
    """执行真实 qwen 日志分类冒烟；返回 0 表示成功。"""
    reset_config()
    cfg = Config()
    if not cfg.llm_base_url or not cfg.llm_api_key:
        print("=" * 60)
        print("真实 LLM 日志分类冒烟")
        print("-" * 60)
        print("未设置 AGENT_LLM_BASE_URL / AGENT_LLM_API_KEY，无法走真实 LLM。")
        print("请设置后重跑（key 只进环境变量）。")
        print("当前不会改动任何代码，仅作说明。")
        return 2

    print("=" * 60)
    print("真实 qwen 日志分类冒烟")
    print(f"base_url : {cfg.llm_base_url}")
    print(f"model    : {cfg.llm_model}")
    print("-" * 60)

    client = create_llm_client(cfg)
    print(f"客户端    : {type(client).__name__}  available={client.available}")
    llm_cls = LLMLogClassifier(llm=client, threshold=cfg.llm_conf_threshold)
    dual = DualLogClassifier(llm_classifier=llm_cls, rule_conf_threshold=cfg.rule_conf_threshold)

    total = len(SAMPLES)
    covered = 0
    print("-" * 60)
    for i, (reason, state, exit_code, note) in enumerate(SAMPLES, 1):
        rec = _rec(reason, state, exit_code)
        result = await dual.aclassify(rec)
        ok = result.is_known
        covered += 1 if ok else 0
        print(f"[{i}/{total}] {note}")
        print(f"    reason : {reason}")
        print(f"    -> {result.category}/{result.subtype} conf={result.confidence:.2f} "
              f"known={result.is_known}  signals={result.signals_hit[:2]}")

    rate = covered / total
    print("-" * 60)
    print(f"LLM 调用次数（仅规则盲区触发）: {dual.llm_calls}（规则可判 4 项应不触发）")
    print(f"覆盖率(规则∪LLM): {covered}/{total} = {rate:.1%}（目标 ≥ 98%，冒烟样本小仅供参考）")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
