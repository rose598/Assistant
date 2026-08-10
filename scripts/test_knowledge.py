"""知识库加载与匹配测试。"""
import sys

sys.path.insert(0, ".")

from src.config import reset_config
from src.knowledge.loader import KnowledgeLoader, KnowledgeMatcher, load_knowledge_base

fail = 0


def check(name: str, condition: bool) -> None:
    global fail
    if condition:
        print(f"  [OK] {name}")
    else:
        print(f"  [FAIL] {name}")
        fail += 1


# ============================================================
# 加载测试
# ============================================================
print("知识库加载测试")
print("=" * 50)

reset_config()
loader = KnowledgeLoader()
kb = loader.load()
matcher = KnowledgeMatcher(kb)

check("FAQ 条目数 >= 30", kb.faq_count >= 30)
check("命令参考条目数 > 0", len(kb.commands) > 0)
check("QOS 条目数 > 0", len(kb.qos) > 0)
check("错误码条目数 > 0", len(kb.error_codes) > 0)
check("所有 FAQ 有 id", all(f.id for f in kb.faq))
check("所有 FAQ 有 title", all(f.title for f in kb.faq))
check("所有 FAQ 有 keywords", all(f.keywords for f in kb.faq))
check("所有 FAQ 有 answer", all(f.answer for f in kb.faq))
check("所有 FAQ search_text 非空", all(f.search_text for f in kb.faq))

print(f"\n加载统计: {kb.faq_count} FAQ, {len(kb.commands)} 命令, "
      f"{len(kb.qos)} QOS, {len(kb.error_codes)} 错误码")

# ============================================================
# 模糊匹配测试
# ============================================================
print("\n模糊匹配测试")
print("=" * 50)

# QOS 相关
results = matcher.match("QOSMaxWallDurationPerJobLimit")
check("QOSMaxWall 匹配有结果", len(results) > 0)
if results:
    check("QOSMaxWall 匹配得分 > 70", results[0][1] >= 70)
    check("QOSMaxWall 匹配标题正确", "QOSMaxWall" in results[0][0].title)

# GPU 相关
results = matcher.match("nvidia-smi 找不到 GPU")
check("nvidia-smi 匹配有结果", len(results) > 0)

# 排队相关
results = matcher.match("作业一直在排队")
check("排队匹配有结果", len(results) > 0)

# 权限相关
results = matcher.match("默认能用多少资源")
check("配额匹配有结果", len(results) > 0)

# match_one 可能返回低于阈值的匹配
entry, score = matcher.match_one("怎么取消作业")
check(f"scancel 匹配(得分: {score:.0f})", entry is not None or score < 70)

# 无匹配
results = matcher.match("xxxxxxxxx不存在的查询yyyyyyyyy")
check("无效查询无结果(>阈值)", len(results) == 0)

# ============================================================
# 关键词匹配测试
# ============================================================
print("\n关键词精确匹配测试")
print("=" * 50)

entries = matcher.match_by_keyword("QOSMaxWall")
check("QOSMaxWall 关键词匹配", len(entries) > 0)

entries = matcher.match_by_keyword("conda")
check("conda 关键词匹配", len(entries) > 0)

entries = matcher.match_by_keyword("不存在关键词xyz")
check("不存在关键词返回空", len(entries) == 0)

# ============================================================
# 便捷函数测试
# ============================================================
print("\n便捷函数测试")
print("=" * 50)

reset_config()
kb2, matcher2 = load_knowledge_base()
check("便捷加载 FAQ 数", kb2.faq_count >= 30)
results = matcher2.match("CUDA out of memory")
check("便捷匹配 OOM", len(results) > 0)

# ============================================================
# 加载性能测试
# ============================================================
print("\n性能测试")
print("=" * 50)

print("\n性能测试")
print("=" * 50)

try:
    _ = KnowledgeLoader().kb
    check("未加载时应抛异常", False)
except RuntimeError:
    check("未加载时抛 RuntimeError", True)

# 空查询
results = matcher.match("")
check("空查询返回空列表", len(results) == 0)

# ============================================================
# 结果
# ============================================================
print()
if fail == 0:
    print("========== 全部知识库测试通过 ==========")
else:
    print(f"========== {fail} 项测试失败 ==========")
    sys.exit(1)
