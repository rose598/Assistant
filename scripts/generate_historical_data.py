"""生成模拟历史作业数据 (200+ 条).

模拟 sacct 输出格式，包含成功/失败作业记录。
字段覆盖推荐系统所需的全部特征。
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta

random.seed(42)

# 配置
NUM_RECORDS = 220
OUTPUT_PATH = "data/historical_jobs.csv"

# 平台参数
PARTITIONS = ["Students", "CPU-6530", "GPU-RTX5090"]
QOS_MAP = {
    "Students": ["qos_stu_default", "qos_stu_small", "qos_stu_medium", "qos_stu_long"],
    "CPU-6530": ["qos_stu_default", "qos_stu_cpu_long"],
    "GPU-RTX5090": ["qos_stu_default", "qos_stu_small", "qos_stu_medium"],
}
STATES = ["COMPLETED", "FAILED", "TIMEOUT", "CANCELLED"]
STATE_WEIGHTS = [0.70, 0.15, 0.10, 0.05]

TASK_TYPES = ["deep_learning", "scientific_computing", "data_analysis", "general"]
TASK_WEIGHTS = [0.35, 0.25, 0.20, 0.20]

JOB_NAMES = {
    "deep_learning": [
        "train_resnet50",
        "train_bert",
        "finetune_gpt2",
        "train_cnn",
        "train_transformer",
        "train_gan",
        "train_diffusion",
        "finetune_llama",
    ],
    "scientific_computing": [
        "md_simulation",
        "dft_calc",
        "monte_carlo",
        "fluid_sim",
        "quantum_chem",
        "molecular_dynamics",
        "ab_initio",
        "fenics_fem",
    ],
    "data_analysis": [
        "pandas_etl",
        "spark_job",
        "jupyter_batch",
        "stat_analysis",
        "data_cleaning",
        "feature_eng",
        "viz_gen",
        "report_gen",
    ],
    "general": [
        "compile_code",
        "run_tests",
        "backup_data",
        "file_process",
        "batch_convert",
        "sync_files",
        "cron_task",
        "misc_script",
    ],
}

# 错误类型（失败作业时）
ERROR_TYPES = [
    "CUDA_OOM",
    "CPU_OOM",
    "TIME_LIMIT",
    "PATH_ERROR",
    "MODULE_NOT_FOUND",
    "PERMISSION_DENIED",
    "CONDA_ERROR",
    "QOS_LIMIT",
]


def random_timestamp(base: datetime, range_days: int = 30) -> datetime:
    """生成随机时间戳."""
    return base - timedelta(
        days=random.randint(0, range_days),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


def generate_record(job_id: int) -> dict[str, str]:
    """生成单条作业记录."""
    base_time = datetime(2025, 6, 15)
    task_type = random.choices(TASK_TYPES, weights=TASK_WEIGHTS, k=1)[0]
    partition = random.choice(PARTITIONS)
    qos = random.choice(QOS_MAP[partition])
    state = random.choices(STATES, weights=STATE_WEIGHTS, k=1)[0]
    job_name = random.choice(JOB_NAMES[task_type])

    # 资源配置
    if partition == "GPU-RTX5090":
        gpus = random.choice([1, 1, 1, 2, 2, 4])
        cpus = random.choice([4, 4, 8, 8, 16])
        mem = random.choice(["16G", "16G", "32G", "32G", "64G"])
        time_limit = random.choice(["04:00:00", "08:00:00", "12:00:00", "24:00:00"])
    elif partition == "CPU-6530":
        gpus = 0
        cpus = random.choice([2, 4, 4, 8, 8])
        mem = random.choice(["4G", "8G", "8G", "16G"])
        time_limit = random.choice(["04:00:00", "12:00:00", "24:00:00", "72:00:00"])
    else:  # Students
        gpus = random.choice([0, 0, 1])
        cpus = random.choice([1, 2, 4, 4])
        mem = random.choice(["4G", "4G", "8G", "16G"])
        time_limit = random.choice(["01:00:00", "04:00:00", "08:00:00"])

    # 时间计算
    submit_time = random_timestamp(base_time)
    wait_minutes = random.randint(0, 120) if state != "CANCELLED" else random.randint(0, 30)
    start_time = submit_time + timedelta(minutes=wait_minutes)

    # 运行时长
    h, m, s = map(int, time_limit.split(":"))
    limit_seconds = h * 3600 + m * 60 + s
    if state == "TIMEOUT":
        elapsed_seconds = int(limit_seconds * random.uniform(0.95, 1.0))
    elif state in ("FAILED", "CANCELLED"):
        elapsed_seconds = random.randint(10, max(60, limit_seconds // 3))
    else:
        elapsed_seconds = random.randint(60, int(limit_seconds * 0.8))

    end_time = start_time + timedelta(seconds=elapsed_seconds)
    exit_code = "0:0" if state == "COMPLETED" else f"1:{random.randint(0, 9)}"

    # 错误信息
    error_msg = ""
    if state == "FAILED":
        error_msg = random.choice(ERROR_TYPES)
    elif state == "TIMEOUT":
        error_msg = "TIME_LIMIT"

    user = f"scc{random.randint(100, 999)}"
    weekday = submit_time.strftime("%A")
    hour = submit_time.hour

    return {
        "job_id": str(job_id),
        "user": user,
        "job_name": job_name,
        "partition": partition,
        "qos": qos,
        "ncpus": str(cpus),
        "ngpus": str(gpus),
        "req_mem": mem,
        "timelimit": time_limit,
        "submit_time": submit_time.isoformat(),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "state": state,
        "exit_code": exit_code,
        "task_type": task_type,
        "wait_time_seconds": str(wait_minutes * 60),
        "elapsed_time_seconds": str(elapsed_seconds),
        "error_type": error_msg,
        "weekday": weekday,
        "hour": str(hour),
    }


def main() -> None:
    """生成 CSV 数据."""
    fields = [
        "job_id",
        "user",
        "job_name",
        "partition",
        "qos",
        "ncpus",
        "ngpus",
        "req_mem",
        "timelimit",
        "submit_time",
        "start_time",
        "end_time",
        "state",
        "exit_code",
        "task_type",
        "wait_time_seconds",
        "elapsed_time_seconds",
        "error_type",
        "weekday",
        "hour",
    ]

    records = [generate_record(10000 + i) for i in range(NUM_RECORDS)]

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    # 统计
    states: dict[str, int] = {}
    for r in records:
        states[r["state"]] = states.get(r["state"], 0) + 1

    print(f"Generated {len(records)} records → {OUTPUT_PATH}")
    print(f"State distribution: {states}")
    print(
        f"Partitions: {sum(1 for r in records if r['partition']=='Students')} Students, "
        f"{sum(1 for r in records if r['partition']=='CPU-6530')} CPU-6530, "
        f"{sum(1 for r in records if r['partition']=='GPU-RTX5090')} GPU-RTX5090"
    )


if __name__ == "__main__":
    main()
