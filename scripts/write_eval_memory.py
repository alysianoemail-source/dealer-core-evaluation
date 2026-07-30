"""
评分引擎输出 → 自动写入记忆系统

功能：
  每次评估完成后调用，自动：
  1. 生成 Markdown 判定记录 → memory/records/
  2. 更新 memory/index.json 索引

用法：
  from write_eval_memory import write_assessment_memory

  result = run_full_assessment(input_data)   # 引擎算分
  write_assessment_memory(result, input_data) # 自动写记忆

也可命令行调用（调试用）：
  python scripts/write_eval_memory.py --name 格力电器 --score 85 --rating A
"""

import json
import sys
import io
from datetime import datetime
from pathlib import Path

# ── Windows GBK 兼容 ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 路径 ──
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
RECORDS_DIR = MEMORY_DIR / "records"
INDEX_FILE = MEMORY_DIR / "index.json"

# 确保目录存在
RECORDS_DIR.mkdir(parents=True, exist_ok=True)

# ── 权重配置（从评分引擎复用） ──
def _get_dim_weights():
    """从 scoring_weights.json 读权重"""
    w_path = PROJECT_DIR / "config" / "scoring_weights.json"
    fallback = {"D1": 15, "D2": 15, "D3": 40, "D4": 30}
    if not w_path.exists():
        return fallback
    with open(w_path, "r", encoding="utf-8") as f:
        w = json.load(f)
    weights = w.get("weights", {})
    dim_map = {
        "dimension_1": "D1", "dimension_2": "D2",
        "dimension_3": "D3", "dimension_4": "D4",
    }
    result = {}
    for key, dim_key in dim_map.items():
        dim = weights.get(key, {})
        result[dim_key] = dim.get("weight_pct", fallback.get(dim_key, 0))
    return result

# ── 信号灯映射 ──
_RATING_SIGNAL = {
    "A": ("🟢 绿灯", "建议准入"),
    "B": ("🟡 黄灯", "建议准入"),
    "C": ("🟠 橙灯", "建议复核"),
    "D": ("🔴 红灯", "建议拒绝"),
}


# ═══════════════════════════════════════════════════════════════
# 核心函数
# ═══════════════════════════════════════════════════════════════

def write_assessment_memory(
    assessment_result: dict,
    input_data: dict = None,
    dealer_name: str = "",
    main_product: str = "",
    data_sources: list = None,
) -> str:
    """
    评分引擎输出 → 写入记忆。

    参数
    ----------
    assessment_result : dict
        run_full_assessment() 的返回值
    input_data : dict, optional
        原始输入数据（用于提取 dealer、主营品类等补充信息）
    dealer_name : str, optional
        经销商名称（可单独传）
    main_product : str, optional
        主营品类（可单独传）
    data_sources : list, optional
        数据来源清单

    返回
    -------
    str : 写入的文件路径（相对项目根）
    """
    # ── 读取基本信息 ──
    company_name = assessment_result.get("company_name", "未知企业")
    industry = assessment_result.get("industry", "未分类")
    is_listed = assessment_result.get("is_listed", False)
    dim_scores = assessment_result.get("dimension_scores", {})
    total_score = assessment_result.get("total_score", 0)
    rating = assessment_result.get("rating", "D")
    rating_label = assessment_result.get("rating_label", "")
    redline_triggered = assessment_result.get("redline_triggered", False)
    redline_details = assessment_result.get("redline_details", {})
    dim_details = assessment_result.get("dimension_details", {})
    data_completeness = assessment_result.get("data_completeness", {})

    # ── 补充信息（从 input_data 或 独立参数） ──
    if not dealer_name and input_data:
        dealer_name = input_data.get("dealer", {}).get("name", "")
    if not main_product and input_data:
        main_product = input_data.get("company", {}).get("main_product", "")

    # ── 生成 ID ──
    record_id = _next_id()

    # ── 信号灯 ──
    signal, admission = _RATING_SIGNAL.get(rating, ("⚪ 未知", "待定"))

    # ── 权重 ──
    weights = _get_dim_weights()

    # ── 生成 Markdown ──
    today_str = datetime.now().strftime("%Y-%m-%d")
    file_name = f"{company_name}_判定记录.md"
    file_path = RECORDS_DIR / file_name

    md = _build_record_md(
        record_id=record_id,
        company_name=company_name,
        dealer_name=dealer_name,
        industry=industry,
        main_product=main_product,
        is_listed=is_listed,
        today_str=today_str,
        dim_scores=dim_scores,
        weights=weights,
        total_score=total_score,
        rating=rating,
        rating_label=rating_label,
        signal=signal,
        admission=admission,
        redline_triggered=redline_triggered,
        redline_details=redline_details,
        dim_details=dim_details,
        data_completeness=data_completeness,
        data_sources=data_sources or [],
    )

    # ── 写入文件 ──
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md)

    # ── 更新索引 ──
    _update_index(company_name, file_name, record_id, today_str)

    # ── 返回相对路径 ──
    rel_path = Path("memory") / "records" / file_name
    print(f"  ✅ 记忆已写入: {rel_path} (ID: {record_id})")
    return str(rel_path)


# ═══════════════════════════════════════════════════════════════
# 内部函数
# ═══════════════════════════════════════════════════════════════

def _next_id() -> str:
    """自动递增记忆ID (MEM-001, MEM-002, ...)"""
    index = _load_index()
    max_num = 0
    for key, rec in index.get("records", {}).items():
        rid = rec.get("id", "")
        if rid.startswith("MEM-"):
            try:
                num = int(rid.split("-")[1])
                if num > max_num:
                    max_num = num
            except ValueError:
                continue
    return f"MEM-{max_num + 1:03d}"


def _load_index() -> dict:
    """加载 index.json，不存在则返回空模板"""
    if INDEX_FILE.exists():
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": "v1.0",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "records": {},
        "batches": {},
        "reviews": {},
    }


def _update_index(company_name: str, file_name: str, record_id: str, today_str: str):
    """追加记录到 index.json"""
    index = _load_index()
    index["version"] = "v1.0"
    index["last_updated"] = today_str
    index["records"][company_name] = {
        "id": record_id,
        "file": f"records/{file_name}",
        "version": "v1.0",
        "created_at": today_str,
        "deleted": False,
    }
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _build_record_md(
    record_id: str,
    company_name: str,
    dealer_name: str,
    industry: str,
    main_product: str,
    is_listed: bool,
    today_str: str,
    dim_scores: dict,
    weights: dict,
    total_score: float,
    rating: str,
    rating_label: str,
    signal: str,
    admission: str,
    redline_triggered: bool,
    redline_details: dict,
    dim_details: dict,
    data_completeness: dict,
    data_sources: list,
) -> str:
    """组装 Markdown 记录"""

    # ── 四维评分表 ──
    dim_table = "| 维度 | 分数 | 权重 |\n|------|------|------|\n"
    dim_order = ["D1", "D2", "D3", "D4"]
    dim_names = {
        "D1": "维度一：行业景气",
        "D2": "维度二：品牌竞争力",
        "D3": "维度三：核企自身信用",
        "D4": "维度四：经销商体系健康度",
    }
    for d in dim_order:
        score = dim_scores.get(d, 0)
        w = weights.get(d, 0)
        dim_table += f"| {dim_names.get(d, d)} | {score} | {w}% |\n"

    # ── 综合结果 ──
    total_display = round(total_score, 2) if total_score else 0
    total_row = (
        f"综合分 | {total_display} / 100 |\n"
        f"评级 | {rating}级（{rating_label}）|\n"
        f"信号灯 | {signal} |\n"
    )
    if redline_triggered:
        total_row += f"一票否决 | ⚠️ 触发 — 评级锁定为 D |\n"
    else:
        total_row += f"一票否决 | 无触发 |\n"

    # ── 红线检查 ──
    redline_rows = ""
    redlines = redline_details.get("checks", {})
    if redlines:
        for key, check in redlines.items():
            triggered = check.get("triggered", False)
            verified = check.get("verified", False)
            label = check.get("label", key)
            if triggered:
                redline_rows += f"- {label}：🚫 **触发** {'(已核实)' if verified else '(待核实)'}\n"
            else:
                redline_rows += f"- {label}：✓ 通过\n"
    else:
        redline_rows = "- 无红线检查记录\n"

    # ── 各维度详细指标得分 ──
    detail_sections = ""
    for d in dim_order:
        details = dim_details.get(d, {}).get("details", {})
        sub = dim_details.get(d, {}).get("sub_dimension_scores", {})
        completeness = data_completeness.get(d, 0)

        if not details:
            detail_sections += f"### {dim_names.get(d, d)}\n\n- 数据完整度：{completeness*100:.0f}%\n- 无明细指标记录\n\n"
            continue

        detail_sections += f"### {dim_names.get(d, d)}\n\n"
        detail_sections += f"**数据完整度**：{completeness*100:.0f}%\n\n"
        detail_sections += "| 指标 | 公司值 | 行业基准 | 得分 |\n|------|--------|---------|------|\n"
        for ind_id, ind_detail in details.items():
            name = ind_detail.get("name", ind_id)
            cv = ind_detail.get("company_value", "-")
            bv = ind_detail.get("benchmark_value", "-")
            score = ind_detail.get("score", "-")
            # 数字格式化
            cv_str = f"{cv:g}" if isinstance(cv, (int, float)) else str(cv)
            bv_str = f"{bv:g}" if isinstance(bv, (int, float)) else str(bv) if bv else "N/A"
            score_str = f"{score:g}" if isinstance(score, (int, float)) else str(score)
            detail_sections += f"| {name} | {cv_str} | {bv_str} | {score_str} |\n"
        detail_sections += "\n"

    # ── 数据来源 ──
    source_rows = ""
    if data_sources:
        for src in data_sources:
            if isinstance(src, dict):
                source_rows += f"| {src.get('name', '')} | {src.get('purpose', '')} |\n"
            else:
                source_rows += f"| {src} | — |\n"

    # ── 完整组装 ──
    md = f"""---
id: {record_id}
type: 企业判定记录
version: v1.0
created_at: {today_str}
created_by: 规则引擎v1.0（自动写入）
superseded_by: null
deleted_at: null
---

# 判定记录：{company_name}

## 基本信息

| 字段 | 内容 |
|------|------|
| 核心企业 | {company_name} |
| 经销商 | {dealer_name or '（未指定）'} |
| 行业 | {industry} |
| 主营品类 | {main_product or '（未指定）'} |
| 上市状态 | {'上市' if is_listed else '非上市'} |
| 评价日期 | {today_str} |
| 规则版本 | v1.0（比率法） |

## 四维评分

{dim_table}
## 综合结果

| 项目 | 内容 |
|------|------|
|{total_row}
## 红线检查

{redline_rows}
## 各维度明细

{detail_sections}"""

    # 数据来源（有则加）
    if data_sources:
        md += """## 数据来源

| 数据源 | 用途 |
|--------|------|
""" + source_rows + "\n"

    # 人工复核占位
    md += """## 人工复核

- 初审人：___（待填写）
- 复核人：___（待填写）
- 终审人：___（待填写）
- 复核意见：___（待填写）
- 复核日期：___（待填写）

---

> 本记录由规则引擎 v1.0 在评估完成后自动写入。
"""

    return md


# ═══════════════════════════════════════════════════════════════
# 命令行入口（调试/手动写入用）
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="手动写入判定记忆")
    parser.add_argument("--name", required=True, help="企业名称")
    parser.add_argument("--score", type=float, default=0, help="综合分")
    parser.add_argument("--rating", default="D", help="评级 (A/B/C/D)")
    parser.add_argument("--industry", default="未分类", help="行业")
    parser.add_argument("--dealer", default="", help="经销商名称")

    args = parser.parse_args()

    # 构建模拟结果（供调试用）
    mock_result = {
        "company_name": args.name,
        "industry": args.industry,
        "is_listed": True,
        "stock_code": "",
        "dimension_scores": {"D1": 75, "D2": 75, "D3": 75, "D4": 75},
        "dimension_details": {
            "D1": {"score": 75, "details": {}, "sub_dimension_scores": {}},
            "D2": {"score": 75, "details": {}, "sub_dimension_scores": {}},
            "D3": {"score": 75, "details": {}, "sub_dimension_scores": {}},
            "D4": {"score": 75, "details": {}, "sub_dimension_scores": {}},
        },
        "total_score": args.score,
        "rating": args.rating,
        "rating_label": {"A": "优秀", "B": "良好", "C": "一般", "D": "不合格"}.get(args.rating, ""),
        "redline_triggered": False,
        "redline_details": {},
        "data_completeness": {"D1": 1.0, "D2": 1.0, "D3": 1.0, "D4": 1.0},
        "vintage_summary": {"vintages": [], "note": ""},
        "effective_weights": {"D1": 15, "D2": 15, "D3": 40, "D4": 30},
    }

    path = write_assessment_memory(mock_result, dealer_name=args.dealer)
    print(f"  文件: {path}")
