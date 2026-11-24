import sys
from pathlib import Path

import pytest

# 让 rule_mining 能以顶层包方式导入（from rule_mining import ...），
# 避免走 newclid 包的完整导入链（需要 numpy/matplotlib 等重依赖）。
# 在完整环境（newclid 已安装）下同样有效。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def row_data():
    """一条合成的数据集行（llm_input_renamed / llm_output_renamed），
    与 generation/dataset/*.jsonl 的行格式一致。"""
    return {
        "llm_input_renamed": (
            "<problem> a : ; b : ; c : perp a b a c [000] ; d : ; "
            "e : eqangle a b c d e [001] ?</problem>"
        ),
        "llm_output_renamed": (
            "<numerical_check> f : cong a b c d [002] ; </numerical_check>"
            "<proof> para a b c d [003] a01 [000] [001] ; "
            "eqratio a b c d e f [004] r34 [003] [002] ; </proof>"
        ),
    }
