"""
从 scoring_functions.json 提取所有指标阈值，输出为可编辑的CSV表格
用法：python scripts/export_thresholds_csv.py
输出：config/scoring_thresholds_table.csv
"""
import json
import csv
import sys
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
INPUT_FILE = CONFIG_DIR / "scoring_functions.json"
OUTPUT_FILE = CONFIG_DIR / "scoring_thresholds_table.csv"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_threshold_rows(data: dict) -> list:
    """提取所有连续型指标的阈值行"""
    rows = []
    indicators = data.get("indicators", {})
    industry_profiles = data.get("industry_profiles", {})

    for group_key, group in indicators.items():
        if group_key.startswith("_"):
            continue  # 跳过说明字段

        for ind_key, ind in group.items():
            if ind_key.startswith("_"):
                continue

            ind_id = ind.get("id", ind_key)
            ind_name = ind.get("name", ind_key)
            dimension = ind.get("dimension", "?")
            sub_dim = ind.get("sub_dimension", "")
            unit = ind.get("unit", "")
            direction = ind.get("direction", "?")

            # ── 离散型指标（lookup 表） ──
            if direction == "discrete" or "lookup" in ind:
                lookup = ind.get("lookup", {})
                base_scores = ind.get("base_scores", {})

                if lookup:
                    for label, score in lookup.items():
                        rows.append({
                            "指标ID": ind_id,
                            "指标名称": ind_name,
                            "维度": dimension,
                            "子维度": sub_dim,
                            "单位": unit,
                            "适用行业": "通用",
                            "方向": direction,
                            "评分方式": "离散对照",
                            "阈值等级": label,
                            "原始值范围": label,
                            "得分": score,
                            "备注": ""
                        })
                elif base_scores:
                    for tier, score in base_scores.items():
                        rows.append({
                            "指标ID": ind_id,
                            "指标名称": ind_name,
                            "维度": dimension,
                            "子维度": sub_dim,
                            "单位": unit,
                            "适用行业": "通用",
                            "方向": direction,
                            "评分方式": "离散对照",
                            "阈值等级": tier,
                            "原始值范围": f"品牌等级={tier}",
                            "得分": score,
                            "备注": ""
                        })
                continue

            # ── 连续型指标（阈值插值） ──
            default_thresholds = ind.get("default_thresholds", [])
            industry_overrides = ind.get("industry_overrides", {})

            # 处理默认阈值（通用行业）
            if default_thresholds:
                rows.extend(_make_threshold_rows(
                    ind_id, ind_name, dimension, sub_dim, unit,
                    "通用（默认）", direction, default_thresholds
                ))

            # 处理行业覆盖阈值
            for industry_key, thresholds in industry_overrides.items():
                industry_name = industry_profiles.get(industry_key, {}).get("name", industry_key)
                rows.extend(_make_threshold_rows(
                    ind_id, ind_name, dimension, sub_dim, unit,
                    industry_name, direction, thresholds
                ))

    return rows


def _make_threshold_rows(ind_id, name, dim, sub_dim, unit, industry, direction, thresholds):
    """把一组阈值数组转为多行（每行一个断点）"""
    rows = []
    # thresholds 格式：[[value, score], [value, score], ...]
    # 已按value降序排列(对于higher_better)或升序(对于lower_better)

    for i, (value, score) in enumerate(thresholds):
        # 生成人类可读的范围描述
        if i == 0:
            if direction == "higher_better":
                range_desc = f"≥ {value}"
            elif direction == "lower_better":
                range_desc = f"≤ {value}"
            else:
                range_desc = f"= {value}（最优）" if direction == "sweet_spot" else f"断点 {value}"
        elif i == len(thresholds) - 1:
            if direction == "higher_better":
                range_desc = f"< {value}"
            else:
                range_desc = f"> {value}"
        else:
            prev_val = thresholds[i-1][0]
            if direction == "higher_better":
                range_desc = f"[{value}, {prev_val})"
            elif direction == "lower_better":
                range_desc = f"({prev_val}, {value}]"
            else:
                range_desc = f"断点 {value}"

        rows.append({
            "指标ID": ind_id,
            "指标名称": name,
            "维度": dim,
            "子维度": sub_dim,
            "单位": unit,
            "适用行业": industry,
            "方向": direction,
            "评分方式": "线性插值",
            "阈值等级": f"第{i+1}档",
            "原始值范围": range_desc,
            "得分": score,
            "备注": ""
        })

    return rows


def main():
    print("📖 读取 scoring_functions.json ...")
    data = load_json(INPUT_FILE)

    print("🔧 提取阈值...")
    rows = extract_threshold_rows(data)

    # 写入CSV
    fieldnames = [
        "指标ID", "指标名称", "维度", "子维度", "单位",
        "适用行业", "方向", "评分方式", "阈值等级",
        "原始值范围", "得分", "备注"
    ]

    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ 已导出 {len(rows)} 行到: {OUTPUT_FILE}")
    print(f"   覆盖指标数: {len(set(r['指标ID'] for r in rows))}")
    print(f"   行业覆盖: {sorted(set(r['适用行业'] for r in rows))}")


if __name__ == "__main__":
    main()
