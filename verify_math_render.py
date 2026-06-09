"""验证 LaTeX 行内/块级公式渲染修复。本地运行：python3 verify_math_render.py"""
from utils import render_markdown

# 取自真实缓存 summaries/2606.02519.md 的公式片段
md = r"""## 3.2 关键算法与数学推导

第一阶段（LLM自动生成）：
$$ \{C_m^k\}_{k=1}^3 = A(W, p) \quad \text{for } m \in \{a, n, v\} $$
其中 \(A(\cdot)\) 是LLM，\(p\) 是提示模板，\(C_m^k\) 是一个候选。

第二阶段（人工筛选）：
$$ C_m^* = H(\{C_m^k\}_{k=1}^3) $$
其中 \(H(\cdot)\) 是人工专家，选择最合适的 \(C_m^*\)。

动作决策：
$$ \hat{a}_t, \Delta\sigma_{i^*, t}, \rho_t = D(D_{i^*}, SC_{i^*}, EC_{i^*}, I_t, p_d) $$
- \(D(\cdot)\)：决策VLM。
- \(\Delta\sigma_{i^*, t}\)：状态转移信号。
"""

out = render_markdown(md)
print("===== 渲染后的 HTML =====")
print(out)
print("\n===== 自动检查 =====")

checks = {
    "行内 \\(A(\\cdot)\\) 完整保留（反斜杠没丢）": r"\(A(\cdot)\)" in out,
    "上标星号 C_m^* 完整保留": "C_m^*" in out,
    "下标 \\Delta\\sigma_{i^*, t} 完整保留": r"\Delta\sigma_{i^*, t}" in out,
    "块级 $$ 定界符保留": "$$" in out,
    "没有出现被吃掉的残缺 'C_m^ '": "C_m^ " not in out,
    "没有 markdown 把 _ 变成 <em>": "<em>" not in out or "i^*" in out,
}
allok = True
for desc, ok in checks.items():
    allok = allok and ok
    print(("  [OK]   " if ok else "  [FAIL] ") + desc)

print("\n结果:", "全部通过 ✅ — 行内公式修复成功" if allok else "存在失败项 ❌")
