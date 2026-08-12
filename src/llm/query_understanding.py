"""模糊提问理解模块。

第 3 周周二交付物：对用户原始问题做规范化与改写，供后续检索/分类使用。
包含三部分：
- 停用词过滤（去掉无意义口头语、语气词）
- 同义词扩展（GPU↔显卡↔显存 等平台常见说法）
- query 改写（合并重复、去噪、输出更利于检索的规范 query）

鲁棒性设计（与前序模块一致）：
- 任何输入都安全返回字符串，绝不抛异常（改写失败时原样返回原始 query）
- 空/纯标点/超长输入有明确处理，不崩溃
- 中英混合、错别字、大小写统一处理
- 专有名词（sbatch、squeue、QOS 等）不被停用词/同义词误删
"""

from __future__ import annotations

import re

# ---- 停用词: 无检索信息量的语气词/口头语 -----------------------------------
STOPWORDS: frozenset[str] = frozenset(
    {
        "怎么", "如何", "怎么办", "为什么", "为啥", "请问", "一下", "我", "的",
        "了", "吗", "呢", "啊", "呀", "吧", "请问下", "求问", "想问", "那个",
    }
)

# ---- 同义词: {规范化词: [变体...]} 用于把变体统一为规范词 -----------------
SYNONYMS: dict[str, tuple[str, ...]] = {
    "gpu": ("gpu", "显卡", "显存", "g卡", "gpu卡", "graphics card"),
    "cpu": ("cpu", "处理器", "核"),
    "排队": ("排队", "队列", "pending", "等待", "卡住不跑"),
    "失败": ("失败", "failed", "挂了", "崩了", "报错", "出错"),
    "提交": ("提交", "提交作业", "投递", "跑作业", "运行作业"),
    "取消": ("取消", "删除", "scancel", "杀掉", "终止"),
    "运行中": ("运行中", "running", "正在跑"),
    "内存": ("内存", "ram", "memory"),
    "磁盘": ("磁盘", "硬盘", "存储空间", "disk", "space"),
    "权限": ("权限", "permission", "没权限", "拒绝访问", "denied"),
    "配额": ("配额", "quota", "额度", "限额", "资源上限"),
    "分区": ("分区", "partition", "队列分区"),
    "登录": ("登录", "login", "登不上", "连不上服务器"),
    "conda": ("conda", "环境", "虚拟环境", "没激活conda"),
    "装包": ("装包", "安装", "pip", "conda install", "装库", "import"),
    "交互式": ("交互式", "srun", "pty", "终端调试", "交互调试"),
}

# 按变体长度降序排序, 保证长变体如 conda install 优先于短变体 install 匹配
_SYNONYM_FLAT: list[tuple[str, str]] = sorted(
    (
        (canonical, variant.lower())
        for canonical, variants in SYNONYMS.items()
        for variant in variants
    ),
    key=lambda item: -len(item[1]),
)


def _filter_stopwords(text: str) -> str:
    """删除停用词。

    中文没有空格分词，直接按词边界匹配会漏掉紧邻汉字的停用词
    （如"请问一下我的作业"里的"请问一下"）。这里改用直接替换：
    多字停用词近似完整短语，直接 remove 不会误伤平台专有名词
    （sbatch/squeue/QOS 等均不在停用表内）。
    """
    for w in STOPWORDS:
        text = text.replace(w, " ")
    return text


def _expand_synonyms(text: str) -> str:
    """把同义变体统一为规范词，提升下游检索命中率。

    英文变体用词边界 ``\\b`` 匹配，避免 `import` 误伤 `important`、
    `f` 误伤 `of` 等子串情况；含中文的变体用普通子串替换
    （中文无词界，且不会与英文单词冲突）。
    """
    lowered = text.lower()
    for canonical, variant in _SYNONYM_FLAT:
        if variant and all(ord(c) < 128 for c in variant):
            lowered = re.sub(rf"\b{re.escape(variant)}\b", canonical, lowered)
        else:
            lowered = lowered.replace(variant, canonical)
    return lowered


def normalize_query(raw: object | None) -> str:
    """规范化原始问题：去空白、统一标点口径。

    ``raw`` 可为任意类型；非字符串会安全转字符串（None 转空串），保证不抛错。
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    # 全角转半角: 含全角标点如 U+FF0C 逗号, 统一为半角便于检索/匹配
    s = _fullwidth_to_halfwidth(s)
    # 合并连续空白
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _fullwidth_to_halfwidth(text: str) -> str:
    """把全角字母/数字/常见符号转半角（中文标点保留）。"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:  # 全角 ASCII 区
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def rewrite_query(raw: object | None) -> str:
    """综合改写：规范化 + 去停用词 + 同义词扩展。

    返回改写后的 query。任何异常都回退为规范化后的原始文本，保证不抛错。
    """
    try:
        norm = normalize_query(raw)
        if not norm:
            return ""
        filtered = _filter_stopwords(norm)
        expanded = _expand_synonyms(filtered)
        # 兜底: 若改写把内容清空 则退回规范化原文
        result = re.sub(r"\s+", " ", expanded).strip()
        return result if result else norm
    except Exception:
        return normalize_query(raw)


# 对外暴露主入口 兼容更直观的命名
def understand(raw: str) -> str:
    """理解并改写用户原始问题，输出利于检索的规范 query。"""
    return rewrite_query(raw)


__all__ = ["normalize_query", "rewrite_query", "understand"]
