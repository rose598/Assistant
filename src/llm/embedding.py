"""向量嵌入模块（mock 先行）。

第 3 周周二交付物：统一的文本嵌入接口 + 确定性 mock 实现。

分工边界（plan §2.3）：真实向量化（BGE-small-zh-v1.5）由 B 负责。
本模块先提供：
- 统一接口 ``embed`` / ``embed_batch``（维度 384，与 BGE-small-zh 一致）
- 确定性 mock 实现：基于文本 tokens 的哈希 + 频率生成假向量，
  保证"同文同向量、近似文本近邻"，从而可测余弦相似度 / 检索链路
- ``cosine_similarity`` 余弦相似度函数
- ``create_embedder`` 工厂：将来接入 BGE / 其他 embedder 时无痛替换

真实模型接入后，只需替换 ``create_embedder`` 的返回实现，上层无需改动。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_DIM = 384  # 与 BAAI/bge-small-zh-v1.5 输出维度一致


class Embedder(Protocol):
    """向量化接口。

    ``dim`` 为输出向量维度；``embed`` 返回单条向量，``embed_batch`` 返回批量。
    """

    dim: int

    def embed(self, text: str) -> list[float]:
        """返回文本的向量表示。"""
        ...

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """返回一批文本的向量表示。"""
        ...


def _tokenize(text: str) -> list[str]:
    """简易分词：中英混排时按"连续汉字/连续 ASCII 词/数字"切分。"""
    try:
        return re.findall(r"[一-鿿]+|[a-zA-Z0-9_]+", text.lower())
    except Exception:
        return []


def _hash_token(token: str, seed: int) -> float:
    """把 token 稳定映射到 [-1, 1] 的确定性值。"""
    h = hashlib.md5(f"{seed}:{token}".encode()).digest()
    return (h[0] / 255.0) * 2.0 - 1.0


@dataclass
class MockEmbedder:
    """确定性 mock 向量化。

    基于 token 频率加权 + 稳定哈希生成固定维度向量。
    特性：
    - 同文 -> 同向量（确定性）
    - 共享 token 多的文本 -> 余弦相似度更高（模拟语义近邻）
    - 维度固定为 ``dim``（默认 384），嵌入结果可复现
    仅为链路测试用，非真实语义向量。
    """

    dim: int = DEFAULT_DIM

    def embed(self, text: str) -> list[float]:
        """返回文本的确定性向量。"""
        tokens = _tokenize(text or "")
        counts = Counter(tokens)
        vec = [0.0] * self.dim
        if not tokens:
            # 空文本 -> 返回全 0 向量 无方向 余弦为 0
            return vec
        for token, freq in counts.items():
            for i in range(self.dim):
                vec[i] += _hash_token(token, i) * freq
        # L2 归一化 保证余弦相似度 <= 1
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """批量向量化。"""
        return [self.embed(t) for t in texts]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度，范围 [-1, 1]。长度不一致或全 0 向量返回 0。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def create_embedder(config: Any | None = None) -> Embedder:
    """工厂：创建 embedding 实现。

    当前返回 mock 实现；未来接入真实 BGE / 本地模型时，只需在此替换，
    上层调用方无需改动。``config`` 预留真实模型参数读取。
    """
    del config  # 预留 真实实现时从配置读取模型路径/服务地址
    return MockEmbedder()


__all__ = ["DEFAULT_DIM", "Embedder", "MockEmbedder", "cosine_similarity", "create_embedder"]
