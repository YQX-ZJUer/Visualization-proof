from rule_mining.dataset_parser import (
    parse_data_row,
    parse_dataset,
    parse_problem_facts,
    parse_proof_relations,
)


def test_parse_problem_facts(row_data):
    facts = parse_problem_facts(row_data["llm_input_renamed"])
    assert facts.get("000", "").startswith("perp")
    assert facts.get("001", "").startswith("eqangle")


def test_parse_data_row_structure(row_data):
    row = parse_data_row(row_data)
    assert row is not None
    nodes = {n["id"]: n for n in row["nodes"]}
    links = row["links"]
    # 事实：000,001,002,003,004；规则：r_a01_1, r_r34_1
    assert nodes["000"]["type"] == "initial_fact"
    assert nodes["003"]["type"] == "derived_fact"
    assert nodes["004"]["type"] == "final_fact"
    assert nodes["r_a01_1"]["type"] == "rule"
    assert nodes["r_a01_1"]["label"] == "a01_1"
    # 前提方向：事实 -> 规则；结论方向：规则 -> 事实
    assert ("000", "r_a01_1") in [(l["source"], l["target"]) for l in links]
    assert ("r_a01_1", "003") in [(l["source"], l["target"]) for l in links]
    # 层次：初始=1，规则=2，结论=3（adjust 后同层前提对齐）
    assert nodes["000"]["layer"] == 1
    assert nodes["r_a01_1"]["layer"] == 2
    assert nodes["003"]["layer"] == 3


def test_parse_proof_relations_missing():
    assert parse_proof_relations("no tags here", {}) is None


def test_parse_dataset(tmp_path, row_data):
    import json

    p = tmp_path / "d.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "llm_input_renamed": row_data["llm_input_renamed"],
                        "llm_output_renamed": row_data["llm_output_renamed"],
                    },
                    ensure_ascii=False,
                ),
                "not a json",
            ]
        ),
        encoding="utf-8",
    )
    rows, report = parse_dataset(str(p))
    assert report["parsed"] == 1
    assert report["json_errors"] == 1
    assert rows[0]["nodes"]
