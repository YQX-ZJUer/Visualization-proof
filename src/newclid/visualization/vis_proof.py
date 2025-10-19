import json
import re
import os
from graphviz import Digraph


def read_and_validate_data(data_path, row_idx):
    """
    读取JSONL格式数据并验证目标行索引的有效性
    
    参数:
        data_path: JSONL文件路径
        row_idx: 需要提取的目标行索引（从0开始）
    
    返回:
        目标行数据（字典），若索引无效则返回None
    """
    # 存储解析成功的JSON数据行
    data_lines = []
    with open(data_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()  # 去除行首尾的空白字符（空格、换行符等）
            if not line:
                continue
            try:
                # 尝试解析当前行为JSON格式
                data = json.loads(line)
                data_lines.append(data)
            except json.JSONDecodeError as e:
                print(f"警告：第{line_num}行JSON格式错误，已跳过 → {str(e)}")

    if row_idx >= len(data_lines):
        print(f"错误：目标行索引{row_idx}超出有效数据范围（共{len(data_lines)}行有效数据）")
        return None
    return data_lines[row_idx]


def extract_facts_from_tag(content, tag_pattern):
    """
    从指定标签包裹的内容中提取带编号的事实(fact)
    
    参数:
        content: 包含标签的原始文本
        tag_pattern: 匹配标签的正则表达式（如r'<problem>(.*?)</problem>'）
    
    返回:
        字典：键为fact的编号（如"001"），值为完整的fact语句（如"cong a b c d [001]"）
    """
    match = re.search(tag_pattern, content, re.DOTALL)  # 使用正则匹配标签及其内容
    if not match:
        return {}
    
    tag_content = match.group(1).strip()  # 提取标签内的内容并去除首尾空白
    stmt_map = {}  # 存储fact的字典：编号→完整语句
    
    # 按分号分割内容为多个片段，过滤空片段并去除首尾空白
    for segment in [s.strip() for s in tag_content.split(';') if s.strip()]:
        parts = [p.strip() for p in segment.split(':') if p.strip()]  # 按冒号分割片段
        # 情况1：片段无法按冒号分割为有效部分（无冒号或分割后部分不足）
        if len(parts) < 2:
            facts = re.findall(r'([^\[\]]+?\[\d{3}\])', segment)  # 匹配非方括号字符+[三位数字]的模式
        # 情况2：片段可按冒号分割（如"a: fact [001]"）
        else:
            # 拼接冒号后的所有部分（处理一个parts中有两个及以上冒号的情况）
            value = ":".join(parts[1:])
            facts = re.findall(r'([^\[\]]+?\[\d{3}\])', value)
        
        # 解析每个fact的编号并存储到字典
        for fact in facts:
            # 提取事实中的三位数字编号（如从"[001]"中提取"001"）
            label_match = re.search(r'\[(\d{3})\]', fact)
            if label_match:
                label = label_match.group(1)
                # 存储编号与事实的映射关系
                stmt_map[label] = fact.strip()
    
    return stmt_map


def parse_problem_facts(llm_input):
    """
    从llm_input_renamed中解析<problem>标签内的初始事实
    """
    return extract_facts_from_tag(llm_input, r'<problem>(.*?)</problem>')  # 调用通用提取函数，传入匹配<problem>标签的正则


def parse_numerical_check_facts(llm_output):
    """
    从llm_output_renamed中解析<numerical_check>标签内的事实
    """
    return extract_facts_from_tag(llm_output, r'<numerical_check>(.*?)</numerical_check>')  # 调用通用提取函数，传入匹配<numerical_check>标签的正则


def parse_proof_relations(llm_output, initial_stmt_map):
    """
    解析<proof>标签中的推导关系，提取结论、规则和前提
    
    参数:
        llm_output: 包含<proof>标签的文本
        initial_stmt_map: 初始事实字典（来自problem和numerical_check）
    
    返回:
        元组(stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes)，其中：
            stmt_map: 包含所有事实的字典
            fact_nodes: 事实节点集合
            rule_nodes: 规则节点集合
            edges: 边的列表（(起点, 终点)）
            node_layer: 节点层次字典（节点→层次数）
            initial_fact_nodes: 初始事实节点集合（未经过推导的事实）
    """
    # 匹配<proof>标签及其内容
    proof_match = re.search(r'<proof>(.*?)</proof>', llm_output, re.DOTALL)
    if not proof_match:
        print("错误：未找到<proof>标签！")
        return None, None, None, None, None, None
    
    proof_content = proof_match.group(1).strip()  # 提取标签内的内容并去除首尾空白
    proof_lines = [line.strip() for line in proof_content.split(';') if line.strip()]  # 按分号分割为独立的推导行
    stmt_map = initial_stmt_map.copy()  # 复制初始fact字典（避免修改原始数据）
    initial_fact_nodes = set(initial_stmt_map.keys())  # 记录初始事实节点（未经过推导的）
    fact_nodes = initial_fact_nodes.copy()  # fact节点集合（初始+推导）
    rule_nodes = set()  # 规则节点集
    edges = []  # 边的列表
    node_layer = {label: 1 for label in fact_nodes}  # 节点层次字典（初始fact的层为1）
    
    # 逐行解析推导步骤
    for line in proof_lines:
        concl_part_match = re.search(r'(.*?\[\d{3}\])', line)  # 提取结论部分（包含[XXX]编号的语句）
        if not concl_part_match:
            print(f"警告：推导行'{line}'未找到结论编号，已跳过")
            continue
        
        concl_part = concl_part_match.group(1).strip()  # 提取结论语句并去除首尾空白
        rule_prem_part = line.replace(concl_part, '', 1).strip()  # 去除结论部分后，剩余内容为规则和前提
        
        # 提取结论的编号
        concl_label_match = re.search(r'\[(\d{3})\]', concl_part)
        if not concl_label_match:
            print(f"警告：结论'{concl_part}'未找到编号，已跳过")
            continue
        
        # 结论编号（如"003"）
        concl_label = concl_label_match.group(1)
        # 将结论添加到事实字典
        stmt_map[concl_label] = concl_part
        # 将结论添加到事实节点集合
        fact_nodes.add(concl_label)
        # 初始化结论节点的层次（若不存在则设为1）
        if concl_label not in node_layer:
            node_layer[concl_label] = 1
        
        # 提取规则名称（行首的单词）
        rule_match = re.search(r'^(\w+)', rule_prem_part)
        if not rule_match:
            print(f"警告：规则前提'{rule_prem_part}'未找到规则名，已跳过")
            continue
        
        # 规则名称（如"a00"、"r61"）
        rule_name = rule_match.group(1)
        # 生成唯一的规则节点标识（避免同一规则多次使用冲突）
        # 格式：r_规则名_序号（如r_a00_1、r_a00_2）
        rule_node = f'r_{rule_name}_{len([rn for rn in rule_nodes if rn.startswith(f"r_{rule_name}")]) + 1}'
        # 将规则节点添加到集合
        rule_nodes.add(rule_node)
        
        # 提取前提编号（所有[XXX]中的数字）
        premise_labels = re.findall(r'(\d{3})', rule_prem_part)
        # 过滤有效的前提（必须存在于事实字典中）
        valid_premises = [p for p in premise_labels if p in stmt_map]
        
        # 若有前提但无有效前提，打印警告
        if not valid_premises and premise_labels:
            print(f"警告：规则'{rule_name}'的前提{premise_labels}中部分未找到对应fact")
        # 若无有效前提，跳过当前推导行
        if not valid_premises:
            continue
        
        # 计算节点层次（确保推导逻辑的垂直顺序）
        # 前提的层次列表
        prem_layers = [node_layer[p] for p in valid_premises]
        # 前提的最大层次
        max_prem_layer = max(prem_layers)
        # 规则层次 = 前提最大层次 + 1（偶数）
        rule_layer = max_prem_layer + 1
        # 结论层次 = 规则层次 + 1（奇数）
        concl_layer = rule_layer + 1
        
        # 更新规则节点和结论节点的层次
        node_layer[rule_node] = rule_layer
        node_layer[concl_label] = concl_layer
        
        # 添加边：前提→规则，规则→结论
        for p in valid_premises:
            edges.append((p, rule_node))  # 前提到规则的边
        edges.append((rule_node, concl_label))  # 规则到结论的边
    
    # 返回解析结果（包含初始事实节点集合）
    return stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes


def adjust_node_layers(rule_nodes, edges, node_layer):
    """
    调整节点层次，确保同一规则的所有前提在同一水平层，优化可视化布局
    
    参数:
        rule_nodes: 规则节点集合
        edges: 边的列表
        node_layer: 原始节点层次字典
    
    返回:
        调整后的节点层次字典
    """
    # 遍历每个规则节点
    for rule_node in rule_nodes:
        # 找到该规则的所有前提节点（边的起点是前提，终点是规则）
        premises = [u for u, v in edges if v == rule_node]
        if not premises:
            continue
            
        # 获取规则节点的层次
        rule_layer = node_layer.get(rule_node, 0)
        # 若规则层次为偶数，调整前提到同一层次
        if rule_layer % 2 == 0:
            # 前提目标层次 = 规则层次 - 1
            target_layer = rule_layer - 1
            # 强制所有前提节点到目标层次
            for p in premises:
                node_layer[p] = target_layer
    return node_layer


def export_to_json(stmt_map, fact_nodes, rule_nodes, edges, node_layer, row_idx, initial_fact_nodes):
    """
    导出节点和边的JSON格式文件，用于d3.js可视化
    
    参数:
        stmt_map: 事实字典（编号→语句）
        fact_nodes: 事实节点集合
        rule_nodes: 规则节点集合
        edges: 边的列表
        node_layer: 节点层次字典
        row_idx: 目标行索引（用于文件名）
        initial_fact_nodes: 初始事实节点集合
    """
    # 构建节点列表
    nodes = []
    
    # 添加事实节点
    for label in fact_nodes:
        # 确定节点类型
        if label in initial_fact_nodes:
            node_type = "initial_fact"
            shape = "ellipse"
        else:
            node_type = "derived_fact"
            shape = "box"
            
        nodes.append({
            "id": label,
            "type": node_type,
            "label": stmt_map[label],
            "layer": node_layer.get(label, 1),
            "shape": shape
        })
    
    # 添加规则节点
    for rule_node in rule_nodes:
        # 提取规则显示名称（去除前缀"r_"）
        rule_label = '_'.join(rule_node.split('_')[1:])
        nodes.append({
            "id": rule_node,
            "type": "rule",
            "label": rule_label,
            "layer": node_layer.get(rule_node, 1),
            "shape": "diamond"
        })
    
    # 构建链接列表
    links = []
    for u, v in edges:
        links.append({
            "source": u,
            "target": v,
            "type": "derivation"
        })
    
    # 构建完整的JSON数据
    json_data = {
        "nodes": nodes,
        "links": links
    }
    
    # 保存JSON文件
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(current_dir, 'json_output')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'proof_row{row_idx}.json')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    
    print(f"JSON数据已生成,保存在:{output_path}")


def create_visualization(stmt_map, fact_nodes, rule_nodes, edges, node_layer, row_idx, initial_fact_nodes):
    """
    使用Graphviz创建可视化图形并保存为SVG文件
    
    参数:
        stmt_map: 事实字典（编号→语句）
        fact_nodes: 事实节点集合
        rule_nodes: 规则节点集合
        edges: 边的列表
        node_layer: 节点层次字典
        row_idx: 目标行索引（用于文件名）
        initial_fact_nodes: 初始事实节点集合（用于区分形状）
    """
    # 初始化Graphviz图形对象：使用dot引擎（层次布局），输出SVG格式
    dot = Digraph(engine='dot', format='svg', name=f'proof_row{row_idx}')
    # 设置全局属性：垂直布局（从上到下），正交边，Arial字体
    dot.attr(rankdir='TB', splines='ortho', fontname='Arial')
    
    # 确定最终节点（层次最高的事实节点）
    if fact_nodes:
        # 提取所有事实节点的层次
        fact_layers = {node: node_layer[node] for node in fact_nodes if node in node_layer}
        # 找到最大层次值
        max_layer = max(fact_layers.values()) if fact_layers else 0
        # 所有处于最大层次的事实节点都是最终节点
        final_nodes = {node for node, layer in fact_layers.items() if layer == max_layer}
    else:
        final_nodes = set()
    
    # 添加事实节点：初始事实为椭圆形，推导事实为矩形，最终节点为绿色
    for label in fact_nodes:
        # 区分初始事实和推导事实的形状
        if label in initial_fact_nodes:
            shape = 'ellipse'  # 初始事实（未推导）→ 椭圆形
        else:
            shape = 'box'      # 推导事实 → 矩形
        
        # 检查是否为最终节点，设置相应颜色
        if label in final_nodes:
            color = 'green'
            fillcolor = 'lightgreen'
        else:
            color = 'blue'
            fillcolor = 'lightblue'
            
        dot.node(
            name=label,                # 节点唯一标识（事实编号）
            label=stmt_map[label],     # 节点显示的文本（完整事实语句）
            shape=shape,               # 形状（根据是否初始事实动态设置）
            color=color,               # 边框颜色
            style='filled',            # 填充样式
            fillcolor=fillcolor        # 填充颜色
        )
    
    # 添加规则节点
    for rule_node in rule_nodes:
        # 提取规则显示名称（去除前缀"r_"）
        rule_label = '_'.join(rule_node.split('_')[1:])
        dot.node(
            name=rule_node,            # 节点唯一标识（规则节点名）
            label=rule_label,          # 节点显示的文本（规则名）
            shape='diamond',           # 形状：菱形
            color='red',               # 边框颜色：红色
            style='filled',            # 填充样式
            fillcolor='pink'           # 填充颜色：粉色
        )
    
    # 添加边（连接节点）
    for u, v in edges:
        dot.edge(u, v)  # 添加从u到v的边
    
    # 确保同一层次的节点水平对齐
    # 获取所有不重复的层次，并排序
    layers = sorted(set(node_layer.values()))
    for layer in layers:
        # 创建子图，设置子图内节点"同一层次"属性
        with dot.subgraph() as sub:
            sub.attr(rank='same')  # 子图内所有节点水平对齐
            # 将当前层次的所有节点添加到子图
            for node in node_layer:
                if node_layer[node] == layer:
                    sub.node(node)
    
    # 保存SVG文件
    # 获取当前脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 定义输出目录（当前目录下的svg_output文件夹）
    output_dir = os.path.join(current_dir, 'svg_output')
    # 创建输出目录（若不存在），exist_ok=True避免目录已存在时报错
    os.makedirs(output_dir, exist_ok=True)
    # 定义输出文件路径（不含后缀）
    output_path = os.path.join(output_dir, f'proof_row{row_idx}')
    
    # 生成并保存SVG文件：view=False（不自动打开），cleanup=True（清理临时文件）
    dot.render(output_path, view=False, cleanup=True)
    print(f"SVG已生成,保存在:{output_path}.svg")


def visualize_single_proof(data_path, row_idx=0):
    """
    主函数：协调各个模块，完成从数据读取到可视化生成的完整流程
    """
    # 1. 读取并验证数据
    data = read_and_validate_data(data_path, row_idx)
    if not data:  
        return
    
    # 2. 提取各类事实
    llm_input = data.get('llm_input_renamed', '')  # 从llm_input_renamed中提取<problem>标签的事实
    problem_facts = parse_problem_facts(llm_input)
    if not problem_facts:  
        print("错误:未找到有效的problem事实")
        return
    
    # 从llm_output_renamed中提取<numerical_check>标签的事实
    llm_output = data.get('llm_output_renamed', '')
    numerical_facts = parse_numerical_check_facts(llm_output)
    
    # 合并所有事实（初始事实 + 补充事实）
    all_facts = {**problem_facts,** numerical_facts}
    
    # 3. 解析证明关系
    result = parse_proof_relations(llm_output, all_facts)
    if not result:  # 解析失败则终止
        return
    # 解包解析结果（包含初始事实节点集合）
    stmt_map, fact_nodes, rule_nodes, edges, node_layer, initial_fact_nodes = result
    
    # 4. 调整节点层次（优化布局）
    node_layer = adjust_node_layers(rule_nodes, edges, node_layer)
    
    # 5. 创建并保存可视化图形（传递初始事实节点集合）
    create_visualization(stmt_map, fact_nodes, rule_nodes, edges, node_layer, row_idx, initial_fact_nodes)
    
    # 6. 导出JSON数据
    export_to_json(stmt_map, fact_nodes, rule_nodes, edges, node_layer, row_idx, initial_fact_nodes)


if __name__ == "__main__":
    DATA_PATH = "/root/autodl-tmp/yaoqixu/NewclidZJU/src/newclid/generation/dataset/geometry_clauses15_samples10k.jsonl"
    visualize_single_proof(DATA_PATH, row_idx=4)
