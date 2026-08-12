"""A/B 测试运行器：纯关键词(A) vs LLM 增强(B) 对比（模拟语料初版）.

用法（在项目目录、配好 AGENT_LLM_* 环境变量后）:
    python scripts/run_ab_test.py

说明:
- A 通道 = PipelineKeywordAdapter（现有知识库关键词匹配，命中返回答案，否则空）。
- B 通道 = LLM（create_llm_client：配真实 key 走 qwen，否则 mock）。
- 语料为【模拟】问法语料（非真实用户），结果仅供横向对比与框架验证，
  不等同于最终验收（正式验收需真实问法语料替换本文件题目）。
- judge 判定"答到要点"：回答包含预期任一核心关键词即算命中。
- scorer 满意度 = 命中关键词占比 [0,1]。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.ab_test import ABResult, run_ab_test_async
from src.api.routes_ask import PipelineKeywordAdapter
from src.config import get_config
from src.llm.mock_llm import create_llm_client

# ---- 模拟问法语料(标注模拟, 正式验收请替换) ----------------------------------


@dataclass
class ABItem:
    """一道 A/B 题."""

    question: str
    expected: list[str]  # 标准答案应包含的核心关键词(命中任一即算答到)


CORPUS: list[ABItem] = [
    # error_diagnosis
    ABItem("CUDA out of memory 怎么办", ["batch size", "显存", "梯度累积"]),
    ABItem("作业一直排队不跑", ["排队", "资源", "QOS", "pending"]),
    ABItem("报错说 Driver/library version mismatch", ["驱动", "nvidia-smi", "版本"]),
    ABItem("conda 找不到环境", ["conda", "激活", "环境"]),
    # job_submission
    ABItem("怎么用 sbatch 提交作业", ["sbatch", "脚本", "提交"]),
    ABItem("如何申请 GPU 跑训练", ["--gres=gpu", "GPU", "sbatch"]),
    ABItem("交互式登录节点调试", ["srun", "--pty", "交互式"]),
    # job_status
    ABItem("怎么看我的作业状态", ["squeue", "状态", "查看"]),
    ABItem("作业卡在 PD 是什么情况", ["PD", "排队", "pending"]),
    ABItem("作业完成后怎么查退出码", ["sacct", "ExitCode", "退出码"]),
    # permission / resource
    ABItem("提示权限不足怎么办", ["权限", "QOS", "配额"]),
    ABItem("怎么升级到更长的运行时间", ["QOS", "时间", "long"]),
    # 口语/同义/边界
    ABItem("显卡不够用", ["GPU", "显存"]),
    ABItem("跑代码说内存不够", ["内存", "--mem"]),
    ABItem("帮我看看这条报错", ["报错", "日志"]),
]


# 更难语料: 需要 107 平台速查知识才能答对(裸 LLM v1 无从得知平台精确名词,
# v2 注入平台速查后能命中) —— 用于量化 v2 的准确率提升, 避开简单语料天花板.
HARD_CORPUS: list[ABItem] = [
    ABItem("默认 QOS 能申请几块 GPU", ["qos_stu_default", "1", "gpu:1"]),
    ABItem("作业最长能设置多久的运行时间", ["qos_stu_long", "72", "3-"]),
    ABItem("想跑 72 小时的深度学习作业用哪个 QOS", ["qos_stu_long", "long", "72"]),
    ABItem("双卡训练实验用哪个 QOS", ["medium_2gpu", "2", "gpu:2"]),
    ABItem("CPU 长任务、数据预处理用什么 QOS", ["cpu_long", "72"]),
    ABItem("申请 4 卡的大型任务用什么 QOS", ["large", "4"]),
    ABItem("查看分区的 CPU/内存限制用哪条命令", ["scontrol", "show part"]),
    ABItem("交互式申请 1 卡 10 分钟怎么起", ["srun", "--gres=gpu:1", "00:10:00"]),
    ABItem("提交作业时显式指定账号用什么参数", ["-A", "account"]),
    ABItem("GPU 分区名叫什么", ["GPU-RTX5090", "Students"]),
    ABItem("判断作业是否真的在跑用什么命令", ["squeue", "R", "运行"]),
    ABItem("取消已提交的作业用什么命令", ["scancel"]),
    ABItem("查看历史作业的退出状态用什么命令", ["sacct"]),
    ABItem("默认运行时间最多几小时", ["4", "qos_stu_default"]),
    ABItem("想用更长时间需要怎么办", ["QOS", "long", "提升"]),
    ABItem("登录节点上直接跑 GPU 任务可以吗", ["sbatch", "登录节点", "--gres"]),
]


def make_qa(hard: bool = False) -> tuple[list[str], list[list[str]]]:
    """拆成 (questions, expected) 两列; hard=True 用更难语料."""
    corpus = HARD_CORPUS if hard else CORPUS
    questions = [it.question for it in corpus]
    expected = [it.expected for it in corpus]
    return questions, expected


# ---- Prompt v2: 注入 107 平台速查(基于 qos_table/slurm_commands) + few-shot ----

PLATFORM_SYSTEM = (
    "你是中国科学技术大学 107 本科生算力平台（基于 Slurm）的智能助手。\n"
    "回答用中文，并尽量引用平台的真实术语/命令，帮助用户。\n"
    "## 平台速查（基于平台文档）\n"
    "分区: Students、CPU-6530、GPU-RTX5090。提交时常用 `sbatch`、交互式用 `srun --pty`。\n"
    "状态: PD=排队, R=运行, CG=收尾, CD=完成, F=失败, CA=取消。\n"
    "查看作业: `squeue -u $USER`; 详情: `scontrol show job <id>`; 历史: `sacct`;\n"
    "日志: `cat <err>` / `tail -n 80 <log>`; 取消: `scancel <id>`。\n"
    "GPU 相关: `--gres=gpu:N` 申请 GPU; CUDA out of memory 常见于显存不足, 先减 batch size。\n"
    "QOS(配额): 默认 qos_stu_default(4CPU/1GPU/4h); 更长用 qos_stu_long(72h);\n"
    "升级运行时间或资源时, 说明 QOS 层级, 需使用对应 `--qos=` 并确认授权。\n"
    "提示权限/配额不足时, 用 `sacctmgr show assoc user=$USER` 检查 QOS 授权, 并确认申请不超配额。"
)

FEW_SHOT: list[tuple[str, str]] = [
    (
        "我的作业一直排队不跑，怎么回事",
        "作业排队（PD）通常因分区/GPU 资源紧张或 QOS 限额未释放。可 `squeue -u $USER` 查看排队详情，降低资源申请量（如 --gres=gpu:1、--mem）或改用空闲分区。",
    ),
    (
        "怎么用 sbatch 提交作业",
        "用 `sbatch` 提交脚本，示例：`sbatch -A <account> -p Students --qos=qos_stu_default -J name -t 00:10:00 -c 1 --wrap 'python train.py'`。注意显式指定 account、大写分区名与正确 QOS。",
    ),
]


def _v2_messages(question: str) -> list[dict[str, str]]:
    """组装 v2 的 OpenAI 风格消息: system(平台速查) + few-shot + 当前问题."""
    msgs: list[dict[str, str]] = [{"role": "system", "content": PLATFORM_SYSTEM}]
    for q, a in FEW_SHOT:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": a})
    msgs.append({"role": "user", "content": question})
    return msgs


# ---- judge / scorer ----------------------------------------------------------


def judge(predicted: object, expected: object) -> bool:
    """predicted 命中 expected 任一核心关键词即答对."""
    text = str(predicted or "").lower()
    return any(k.lower() in text for k in (expected or []))


def scorer(predicted: object, expected: object) -> float:
    """满意度 = 命中关键词占比 [0,1]."""
    text = str(predicted or "").lower()
    keys = [k for k in (expected or []) if k]
    if not keys:
        return 0.0
    return sum(1 for k in keys if k.lower() in text) / len(keys)


# ---- 通道 ----------------------------------------------------------


def make_pipeline_keyword():
    """A 通道: 关键词匹配, 命中返回答案文本, 未命中返回空串."""
    adapter = PipelineKeywordAdapter()

    def fn(question: str) -> str:
        hit = adapter.match(question)
        return hit.answer if hit else ""

    return fn


def make_pipeline_llm():
    """B 通道 v1: LLM 裸答该问题(真实 qwen 或 mock)."""
    config = get_config()
    client = create_llm_client(config)

    async def fn(question: str) -> str:
        resp = await client.complete([{"role": "user", "content": question}])
        return resp.text

    return fn


def make_pipeline_llm_v2():
    """B 通道 v2: LLM + 107 平台速查 system + few-shot 增强."""
    config = get_config()
    client = create_llm_client(config)

    async def fn(question: str) -> str:
        resp = await client.complete(_v2_messages(question))
        return resp.text

    return fn


def _fmt(result: ABResult, title: str = "A/B 测试结果（模拟语料初版）") -> str:
    lines = [
        title,
        f"  题数         : {result.total}",
        f"  A(关键词)acc : {result.accuracy_a:.1%}  (命中 {result.correct_a})",
        f"  B(LLM)  acc  : {result.accuracy_b:.1%}  (命中 {result.correct_b})",
        f"  A 满意度     : {result.mean_score_a:.2f}",
        f"  B 满意度     : {result.mean_score_b:.2f}",
        f"  胜出方       : {result.winner}",
        f"  准确率提升   : {result.improvement:.1%}",
    ]
    # 逐题明细
    lines.append("  逐题明细:")
    for trial in result.outcomes:
        lines.append(f"    [{trial.branch}] {'√' if trial.correct else '×'} {trial.question[:22]}")
    return "\n".join(lines)


async def main(hard: bool = False, only_v2: bool = False) -> None:
    questions, expected = make_qa(hard=hard)

    def make_progress(label: str):
        def _p(done: int, total: int) -> None:
            print(f"  [进度] {label} {done}/{total}", flush=True)

        return _p

    if not only_v2:
        # 对比①: A(关键词) vs B v1(裸 LLM)
        r1 = await run_ab_test_async(
            questions,
            expected,
            make_pipeline_keyword(),
            make_pipeline_llm(),
            judge=judge,
            scorer=scorer,
            progress=make_progress("① A vs Bv1"),
        )
        print(_fmt(r1, "A/B 测试①: A(关键词) vs B(裸 LLM)"))
        print()

    # 对比②: B v1(裸 LLM) vs B v2(平台速查增强) —— 量化 Prompt v2 提升
    r2 = await run_ab_test_async(
        questions,
        expected,
        make_pipeline_llm(),
        make_pipeline_llm_v2(),
        judge=judge,
        scorer=scorer,
        progress=make_progress("② Bv1 vs Bv2"),
    )
    print(_fmt(r2, "A/B 测试②: B v1(裸 LLM) vs B v2(平台速查增强)"))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hard", action="store_true", help="用更难语料量化 v2(需真实 key 才有意义)"
    )
    parser.add_argument("--only-v2", action="store_true", help="只跑测试②(v1 vs v2), 省一半调用")
    args = parser.parse_args()
    asyncio.run(main(hard=args.hard, only_v2=args.only_v2))
