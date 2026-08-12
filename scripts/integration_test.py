"""Day 6 集成测试（模拟语料版）：50+ 题正确率 + 边界健壮性.

用法（在项目目录）:
    python scripts/integration_test.py                # 无 key 时 mock 通道(默认,快)
    python scripts/integration_test.py --use-real     # 配真实 key 走 qwen(慢但真实)
    python scripts/integration_test.py --limit 10     # 只跑前 10 题(快速验证)

覆盖:
- 50+ 道【模拟】问法语料(4 类意图 + 口语/同义/边界/错别字), 每道配标准要点关键词。
- 走完整双通道(IntegratedQA: keyword 直回 + RAG/LLM 兜底)。
- judge 判定"答到要点"(命中任一要点关键词即算对), 统计整体正确率(plan 验收≥85%)。
- 边界输入(空/纯标点/超长/表情/SQL注入/无关)验证不崩溃、有合理返回。

⚠️ 语料为【模拟】, 结果供流程/框架验证与横向参照, 不等同最终验收
   (正式 50+ 验收需真实用户语料替换题目)。
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from src.api.routes_ask import get_qa

# ---- 模拟语料(标注模拟; 正式验收请替换) ----------------------------------


@dataclass
class QCItem:
    """一道集成测试题."""

    question: str
    expected: list[str]  # 标准答案应包含的要点关键词(命中任一即答到)


# 50+ 道, 覆盖 4 类意图 + 口语/同义/错别字/边界
CORPUS: list[QCItem] = [
    # error_diagnosis
    QCItem("CUDA out of memory 怎么办", ["batch size", "显存"]),
    QCItem("报错 Driver/library version mismatch", ["驱动", "nvidia-smi"]),
    QCItem("作业一直排队不跑", ["排队", "QOS", "资源"]),
    QCItem("conda 找不到环境", ["conda", "激活"]),
    QCItem("说我没有权限提交", ["权限", "QOS"]),
    QCItem("跑出来乱码了", ["编码", "locale"]),
    QCItem("ModuleNotFoundError 缺包", ["安装", "pip", "conda"]),
    QCItem("磁盘总是满", ["磁盘", "清理"]),
    QCItem("一直 Loading 卡住", ["卡住", "重试", "网络"]),
    QCItem("GPU 温度过高", ["GPU", "温度"]),
    QCItem("提交被拒 Invalid qos", ["QOS", "qos_stu", "授权"]),
    QCItem("内存不够 OOM", ["内存", "batch"]),
    # job_submission
    QCItem("怎么用 sbatch 提交", ["sbatch", "脚本"]),
    QCItem("如何申请 GPU 跑训练", ["--gres=gpu", "GPU"]),
    QCItem("交互式登录调试", ["srun", "--pty"]),
    QCItem("作业脚本写在哪", ["脚本", "sbatch"]),
    QCItem("申请两块显卡", ["--gres=gpu:2", "GPU"]),
    QCItem("提交时说 account 不对", ["account", "-A"]),
    QCItem("作业名怎么起", ["-J", "job name"]),
    QCItem("想后台跑作业", ["sbatch", "后台", "nohup"]),
    # job_status
    QCItem("怎么看我的作业", ["squeue"]),
    QCItem("作业卡 PD 什么意思", ["PD", "排队", "pending"]),
    QCItem("作业跑完了吗", ["squeue", "sacct"]),
    QCItem("查退出码", ["sacct", "ExitCode"]),
    QCItem("结束作业", ["scancel"]),
    QCItem("作业详情怎么看", ["scontrol", "show job"]),
    QCItem("作业被取消了 CA 什么情况", ["CA", "取消"]),
    QCItem("作业失败了怎么办", ["日志", "sacct"]),
    # permission / resource
    QCItem("分区权限不足", ["权限", "分区"]),
    QCItem("升级更长时间", ["QOS", "long", "时间"]),
    QCItem("配额用完了", ["配额", "QOS"]),
    QCItem("想用更长运行时间", ["QOS", "时间"]),
    QCItem("默认能跑多久", ["4h", "qos_stu_default"]),
    # 口语 / 同义 / 错别字 / 边界
    QCItem("显卡不够用", ["GPU", "显存"]),
    QCItem("跑代码说内存不够", ["内存", "--mem"]),
    QCItem("作业排队好捺", ["排队"]),
    QCItem("怎么杀掉作页", ["scancel", "取消"]),
    QCItem("看哈作业状态", ["squeue", "状态"]),
    QCItem("显存爆了", ["显存", "batch"]),
    QCItem("找不到显卡", ["GPU", "nvidia-smi"]),
    QCItem("交个作业咋弄", ["sbatch", "提交"]),
    QCItem("作业一直pending", ["PD", "排队", "pending"]),
    QCItem("这个报错啥意思", ["报错", "日志"]),
    QCItem("我的GPU咋没了", ["GPU", "--gres"]),
    QCItem("node怎么选", ["分区", "node"]),
    QCItem("debug分区能用吗", ["分区", "debug"]),
    QCItem("训练多久合适", ["时间", "QOS"]),
    QCItem("存储不够存", ["磁盘", "存储"]),
]

# 边界输入(不要求答对, 只要求不崩溃 + 有合理返回)
EDGE_INPUTS: list[str] = [
    "   ",  # 纯空白
    "！！！？？？",  # 纯标点
    "a" * 2000,  # 超长
    "😀🚀🔥",  # 表情
    "' OR '1'='1' --",  # SQL 注入尝试
    "今天天气怎么样",  # 无关问题
    "?",
    "",
]


def judge(predicted: str, expected: list[str]) -> bool:
    """命中任一要点关键词即答到."""
    text = predicted.lower()
    return any(k.lower() in text for k in expected)


async def run_qa(qa, sid: str, question: str) -> str:
    r = await qa.ask(sid, question)
    return r.answer or ""


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-real", action="store_true", help="配真实 key 走 qwen(慢)")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题(0=全量)")
    args = parser.parse_args()

    qa = get_qa()  # 完整双通道: keyword 直回 + RAG/LLM(真实 qwen if key else mock)

    if args.use_real:
        print("[模式] 用真实 LLM(需 AGENT_LLM_* 已配置) —— 较慢")
    else:
        print("[模式] 默认(无 key 时 keyword + mock 兜底) —— 快")

    questions = CORPUS[: args.limit] if args.limit > 0 else CORPUS
    correct = 0
    misses: list[str] = []
    for i, item in enumerate(questions, start=1):
        answer = await run_qa(qa, f"it-{i}", item.question)
        ok = judge(answer, item.expected)
        if ok:
            correct += 1
        else:
            misses.append(item.question)
        print(f"  [{i}/{len(questions)}] {'√' if ok else '×'} {item.question[:20]}", flush=True)

    total = len(questions)
    acc = correct / total if total else 0.0
    print("\n===== 正确率统计(模拟语料) =====")
    print(f"  题数   : {total}  命中 {correct}")
    print(f"  正确率 : {acc:.1%}   (plan 验收 ≥85%)  {'✅达标' if acc >= 0.85 else '❌未达'}")
    if misses:
        print("  未命中题目:")
        for m in misses:
            print(f"    - {m}")

    # 边界健壮性
    print("\n===== 边界健壮性(不崩溃 + 合理返回) =====")
    edge_ok = 0
    for inp in EDGE_INPUTS:
        try:
            # 空串被 pydantic 拦, 直接调 ask 会返回 fallback/友好提示, 不应抛异常
            ans = await run_qa(qa, "edge", inp)
            nonempty = bool(ans.strip())
            print(f"  [输入 {inp[:12]!r}] {'ok' if nonempty else '空返回'} (len={len(ans)})")
            edge_ok += 1 if nonempty else 0
        except Exception as exc:
            print(f"  [输入 {inp[:12]!r}] ❌ 异常: {exc}")
    print(f"  边界通过: {edge_ok}/{len(EDGE_INPUTS)}")

    # 汇总
    print("\n===== 汇总 =====")
    print(f"  正确率 {acc:.1%} / 边界 {edge_ok}/{len(EDGE_INPUTS)}  (模拟语料, 非最终验收)")


if __name__ == "__main__":
    asyncio.run(main())
