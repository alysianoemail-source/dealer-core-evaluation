"""
规则引擎 — 经销商核企评分计算
version: v1.0  (2026-07-26)

核心变更（v0.2 → v1.0）:
  - 打分逻辑从"绝对值阈值"改为"行业基准比率"：分数 = f(公司值 ÷ 行业基准值)
  - 行业基准值来源：iFinD EDB全行业平均值 > 同行业上市公司中位数 > 转人工
  - 阈值表通用化：config/scoring_thresholds.json 定义比率→分数映射（所有行业共用）
  - 行业差异由模板驱动：config/industry_templates/{industry}.json 定义看哪些指标

设计原则:
  - AI不打分：评分由本引擎独立计算，LLM仅做文字组织
  - 数据驱动：修改阈值只需改JSON，不需要改代码
  - 可追溯：每个分数都可还原为"该指标是行业基准的X倍"
"""

import json
import math
import sys
import io
from pathlib import Path
from typing import Optional, Union, Dict, List, Tuple

# ── Windows GBK 兼容 ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 路径 ──
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
TEMPLATE_DIR = CONFIG_DIR / "industry_templates"
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

# ── 全局缓存 ──
_THRESHOLDS = None       # scoring_thresholds.json
_WEIGHTS = None           # scoring_weights.json
_EDB_MAP = None           # edb_indicator_map.json
_TEMPLATES = {}           # industry_templates/*.json (按需加载)


# ═══════════════════════════════════════════════════════════════
# 第0层：配置加载 + 工具函数
# ═══════════════════════════════════════════════════════════════

def _load_thresholds():
    """加载比率→分数映射表"""
    global _THRESHOLDS
    if _THRESHOLDS is None:
        with open(CONFIG_DIR / "scoring_thresholds.json", "r", encoding="utf-8") as f:
            _THRESHOLDS = json.load(f)
    return _THRESHOLDS


def _load_weights():
    """加载权重配置"""
    global _WEIGHTS
    if _WEIGHTS is None:
        with open(CONFIG_DIR / "scoring_weights.json", "r", encoding="utf-8") as f:
            _WEIGHTS = json.load(f)
    return _WEIGHTS


def _load_edb_map():
    """加载EDB指标映射"""
    global _EDB_MAP
    if _EDB_MAP is None:
        with open(CONFIG_DIR / "edb_indicator_map.json", "r", encoding="utf-8") as f:
            _EDB_MAP = json.load(f)
    return _EDB_MAP


def _load_template(industry: str) -> dict:
    """加载行业模板（按需+缓存）"""
    global _TEMPLATES
    if industry not in _TEMPLATES:
        # 尝试匹配文件名
        template_path = TEMPLATE_DIR / f"{industry}.json"
        if not template_path.exists():
            # 模糊匹配
            candidates = list(TEMPLATE_DIR.glob("*.json"))
            for c in candidates:
                t = json.load(open(c, "r", encoding="utf-8"))
                if t.get("industry", {}).get("name") == industry:
                    template_path = c
                    break
            else:
                # 加载 default
                template_path = TEMPLATE_DIR / "default.json"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                _TEMPLATES[industry] = json.load(f)
        else:
            raise FileNotFoundError(f"行业模板未找到: {industry} (tried: {template_path})")
    return _TEMPLATES[industry]


def _safe_mean(values: list, weights: list = None) -> Optional[float]:
    """加权平均，忽略None/NaN"""
    if weights is None:
        weights = [1] * len(values)
    total_w, total_v = 0.0, 0.0
    for v, w in zip(values, weights):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        total_v += v * w
        total_w += w
    return total_v / total_w if total_w > 0 else None


def _interpolate(value: float, thresholds: list) -> float:
    """
    线性插值：在一组 [ratio_min, score] 断点之间插值。
    thresholds 已按 ratio_min 从大到小排列（higher_better）。
    value 是比率（公司值/基准值）。
    """
    if not thresholds:
        return 0.0

    # 高于最高断点
    if value >= thresholds[0]["ratio_min"]:
        return float(thresholds[0]["score"])

    # 低于最低断点
    if value <= thresholds[-1]["ratio_min"]:
        return float(thresholds[-1]["score"])

    # 在中间插值
    for i in range(len(thresholds) - 1):
        upper, lower = thresholds[i], thresholds[i + 1]
        if lower["ratio_min"] <= value <= upper["ratio_min"]:
            if upper["ratio_min"] == lower["ratio_min"]:
                return float(upper["score"])
            ratio = (value - lower["ratio_min"]) / (upper["ratio_min"] - lower["ratio_min"])
            return lower["score"] + ratio * (upper["score"] - lower["score"])

    return float(thresholds[-1]["score"])


def _ratio_to_score(ratio: float, direction: str, thresholds_map: dict) -> Optional[float]:
    """
    通用比率→分数映射。

    参数:
      ratio: 公司值/行业基准值
      direction: higher_better | lower_better
      thresholds_map: scoring_thresholds.json中的mappings
    """
    if ratio is None or (isinstance(ratio, float) and math.isnan(ratio)):
        return None

    mapping = thresholds_map.get(direction)
    if not mapping:
        return None

    thresholds = mapping["thresholds"]
    interpolation_enabled = thresholds_map.get("ratio_interpolation", {}).get("enabled", True)

    if interpolation_enabled:
        return _interpolate(ratio, thresholds)

    # 不插值，取最近匹配
    for t in thresholds:
        if ratio >= t["ratio_min"]:
            return float(t["score"])
    return float(thresholds[-1]["score"])


def _sweet_spot_score(value: float, optimal_min: float, optimal_max: float) -> float:
    """适中最优型打分：在最优区间内最高，偏离扣分。"""
    if optimal_min <= value <= optimal_max:
        return 95.0

    mid = (optimal_min + optimal_max) / 2
    deviation = abs(value - mid) / mid

    if deviation <= 0.10:
        return 80.0
    elif deviation <= 0.20:
        return 65.0
    elif deviation <= 0.40:
        return 45.0
    else:
        return 20.0


# ═══════════════════════════════════════════════════════════════
# 第1层：单指标评分
# ═══════════════════════════════════════════════════════════════

def score_ratio_indicator(
    company_value: Optional[float],
    benchmark_value: Optional[float],
    direction: str,
    indicator_id: str = ""
) -> Optional[float]:
    """
    比率型指标打分（核心函数）。

    输入:
      company_value: 公司实际值
      benchmark_value: 行业基准值（EDB全行业均值/上市公司中位数等）
      direction: higher_better | lower_better

    输出:
      0-100 的分数，或 None（数据不足以打分）
    """
    if company_value is None or benchmark_value is None:
        return None

    if benchmark_value == 0:
        # 行业基准为0（如行业ROE均值为0），回退方案标记
        return None

    thresholds = _load_thresholds()

    if direction == "higher_better":
        ratio = company_value / benchmark_value
        score = _ratio_to_score(ratio, "higher_better", thresholds["mappings"])
    elif direction == "lower_better":
        # 越低越好：ratio = 基准/公司（使方向与higher_better一致）
        ratio = benchmark_value / company_value
        score = _ratio_to_score(ratio, "higher_better", thresholds["mappings"])
    else:
        score = None

    return score


def score_discrete_indicator(
    value: any,
    lookup: dict,
    default: float = None
) -> Optional[float]:
    """离散型指标：直接查映射表。"""
    if value is None:
        return default
    return lookup.get(value, default)


def score_sweet_spot_indicator(
    company_value: Optional[float],
    optimal_min: float,
    optimal_max: float
) -> Optional[float]:
    """适中最优型指标：资产负债率等。"""
    if company_value is None:
        return None
    return _sweet_spot_score(company_value, optimal_min, optimal_max)


def score_direct_indicator(
    company_value: Optional[float],
    max_value: float,
    min_value: float = 0,
    direction: str = "higher_better"
) -> Optional[float]:
    """
    直接映射型：已知取值范围时线性映射到0-100。
    用于实缴比例（0-100%）、成立年限（0-30年）等。
    """
    if company_value is None:
        return None
    if max_value == min_value:
        return 50.0

    if direction == "higher_better":
        clamped = max(min_value, min(company_value, max_value))
        return (clamped - min_value) / (max_value - min_value) * 100
    else:
        clamped = max(min_value, min(company_value, max_value))
        return (max_value - clamped) / (max_value - min_value) * 100


# ═══════════════════════════════════════════════════════════════
# 第2层：子维度合成
# ═══════════════════════════════════════════════════════════════

def _compose_sub_dimension(scores: Dict[str, Optional[float]]) -> Optional[float]:
    """子维度分数 = 各指标分数的简单平均（忽略None）"""
    valid = [v for v in scores.values() if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


# ═══════════════════════════════════════════════════════════════
# 第3层：四维度计算
# ═══════════════════════════════════════════════════════════════

def compute_dimension_1(data: dict, industry: str, is_listed: bool) -> dict:
    """
    D1 行业景气（15%）

    数据结构(data)示例:
    {
      "d1_revenue_growth": {"company_value": -9.89, "benchmark_value": 6.4},
      "d1_roe": {"company_value": 20.3, "benchmark_value": 3.2},
      ...
    }
    """
    template = _load_template(industry)
    d1_cfg = template["dimension_1"]["sub_dimensions"]
    details = {}

    # ── 基本面（50%）──
    fundamental_scores = {}
    for ind in d1_cfg["基本面"]["indicators"]:
        ind_data = data.get(ind["id"], {})
        cv = ind_data.get("company_value")
        bv = ind_data.get("benchmark_value")
        direction = ind.get("direction", "higher_better")

        if direction == "sweet_spot":
            ss = ind.get("sweet_spot", {"min": 40, "max": 60})
            score = score_sweet_spot_indicator(cv, ss["min"], ss["max"])
        else:
            score = score_ratio_indicator(cv, bv, direction, ind["id"])

        fundamental_scores[ind["id"]] = score
        details[ind["id"]] = {
            "name": ind["name"], "company_value": cv, "benchmark_value": bv,
            "benchmark_vintage": ind_data.get("benchmark_vintage", ""),
            "score": score, "direction": direction
        }

    fundamental_avg = _compose_sub_dimension(fundamental_scores)

    # ── 量价领先（30%）──
    pv_scores = {}
    for ind in d1_cfg["量价领先"]["indicators"]:
        ind_data = data.get(ind["id"], {})
        cv = ind_data.get("company_value")
        bv = ind_data.get("benchmark_value")
        direction = ind.get("direction", "higher_better")
        score = score_ratio_indicator(cv, bv, direction, ind["id"])
        pv_scores[ind["id"]] = score
        details[ind["id"]] = {
            "name": ind["name"], "company_value": cv, "benchmark_value": bv,
            "score": score, "direction": direction
        }

    pv_avg = _compose_sub_dimension(pv_scores)

    # 量价修正
    pv_adjustment = 0
    pv_adjust_rules = d1_cfg["量价领先"].get("price_volume_adjustment", {}).get("rules", {})
    volume_dir = data.get("_volume_direction", "")   # "up"/"down"/""
    price_dir = data.get("_price_direction", "")     # "up"/"down"/""
    direction_key = f"volume_{volume_dir}_price_{price_dir}"
    if direction_key in pv_adjust_rules:
        pv_adjustment = pv_adjust_rules[direction_key]["adjustment"]

    # ── 市场预期（20%）──
    expectation_scores = {}
    for ind in d1_cfg["市场预期"]["indicators"]:
        ind_data = data.get(ind["id"], {})
        cv = ind_data.get("company_value")
        bv = ind_data.get("benchmark_value")
        direction = ind.get("direction", "higher_better")

        if ind.get("benchmark_method") == "discrete":
            lookup = ind.get("lookup", {})
            score = score_discrete_indicator(cv, lookup)
        elif direction == "lower_better":
            # PE分位：直接映射（越低越好，分位就是排名）
            score = score_direct_indicator(cv, max_value=100, direction="lower_better") if cv is not None else None
        else:
            score = score_ratio_indicator(cv, bv, direction, ind["id"])

        expectation_scores[ind["id"]] = score
        details[ind["id"]] = {
            "name": ind["name"], "company_value": cv, "benchmark_value": bv,
            "score": score, "direction": direction
        }

    expectation_avg = _compose_sub_dimension(expectation_scores)

    # ── 外生调整 ──
    external_adjust = data.get("_external_adjustment", 0)
    max_adjust = template["dimension_1"]["sub_dimensions"]["外生调整"]["max_adjustment"]
    external_adjust = max(-max_adjust, min(external_adjust, max_adjust))

    # ── 合成 ──
    d1_score = _safe_mean(
        [fundamental_avg, pv_avg + pv_adjustment, expectation_avg],
        [50, 30, 20]
    )
    if d1_score is not None:
        d1_score = min(100, max(0, d1_score + external_adjust))

    return {
        "score": round(d1_score, 1) if d1_score else None,
        "sub_scores": {
            "基本面": round(fundamental_avg, 1) if fundamental_avg else None,
            "量价领先": round(pv_avg, 1) if pv_avg else None,
            "量价修正": pv_adjustment,
            "市场预期": round(expectation_avg, 1) if expectation_avg else None,
            "外生调整": external_adjust
        },
        "details": details
    }


def compute_dimension_2(data: dict, industry: str, is_listed: bool) -> dict:
    """
    D2 品牌竞争力（15%）

    通用逻辑，跨行业一致。
    品牌等级S/A/B/C + 品牌财务 + 创新口碑
    """
    template = _load_template(industry)
    d2_cfg = template["dimension_2"]["sub_dimensions"]
    details = {}

    # ── 市场地位（50%）──
    brand_tier = data.get("d2_brand_tier", "")
    tier_lookup = {"S": 93, "A": 80, "B": 60, "C": 35}
    brand_score = score_discrete_indicator(brand_tier, tier_lookup)
    details["d2_brand_tier"] = {"name": "品牌等级", "value": brand_tier, "score": brand_score}

    market_share = data.get("d2_market_share", {})
    ms_score = market_share.get("score")  # 外部传入（来自WebSearch市场份额排名）
    details["d2_market_share"] = {"name": "市场份额", "value": market_share.get("rank", ""), "score": ms_score}
    market_avg = _safe_mean([brand_score, ms_score])

    # ── 品牌财务（30%）──
    weights_cfg = _load_weights()
    if is_listed:
        bf_scores = {}
        for ind in d2_cfg["品牌财务"]["indicators"]:
            if not ind.get("listed_only", True):
                continue
            ind_data = data.get(ind["id"], {})
            cv = ind_data.get("company_value")
            bv = ind_data.get("benchmark_value")
            score = score_ratio_indicator(cv, bv, "higher_better", ind["id"])
            bf_scores[ind["id"]] = score
            details[ind["id"]] = {"name": ind["name"], "company_value": cv, "benchmark_value": bv, "score": score}
        brand_finance_avg = _compose_sub_dimension(bf_scores)
    else:
        # 非上市：代理指标 × 0.80
        proxy = data.get("d2_proxy", {})
        proxy_scores = {
            "rank": score_direct_indicator(proxy.get("revenue_rank_score"), 100),
            "tax": score_direct_indicator(proxy.get("tax_score"), 100),
            "bidding": score_direct_indicator(proxy.get("bidding_score"), 100)
        }
        brand_finance_avg = _safe_mean(list(proxy_scores.values()), [0.4, 0.3, 0.3])
        if brand_finance_avg is not None:
            brand_finance_avg *= 0.80  # 非上市降权
        details["d2_proxy"] = {"name": "品牌财务(非上市代理)", "score": brand_finance_avg}

    # ── 创新口碑（20%）──
    innovation_scores = {}
    for ind in d2_cfg["创新口碑"]["indicators"]:
        ind_data = data.get(ind["id"], {})
        if ind.get("benchmark_method") == "discrete":
            score = score_discrete_indicator(ind_data.get("company_value"), ind.get("lookup", {}))
        else:
            cv = ind_data.get("company_value")
            bv = ind_data.get("benchmark_value")
            score = score_ratio_indicator(cv, bv, "higher_better", ind["id"])
        innovation_scores[ind["id"]] = score
        details[ind["id"]] = {"name": ind["name"], "company_value": ind_data.get("company_value"), "score": score}

    innovation_avg = _compose_sub_dimension(innovation_scores)

    # ── 合成 ──
    d2_score = _safe_mean([market_avg, brand_finance_avg, innovation_avg], [50, 30, 20])

    # 特殊规则
    if data.get("_no_authorization"):
        d2_score = min(d2_score or 0, 30)
    if data.get("_counterfeit_brand"):
        d2_score = 0

    return {
        "score": round(d2_score, 1) if d2_score else None,
        "sub_scores": {
            "市场地位": round(market_avg, 1) if market_avg else None,
            "品牌财务": round(brand_finance_avg, 1) if brand_finance_avg else None,
            "创新口碑": round(innovation_avg, 1) if innovation_avg else None
        },
        "details": details
    }


def compute_dimension_3(data: dict, industry: str, is_listed: bool, redline_result: dict = None) -> dict:
    """
    D3 核企自身信用（40%，最高权重）

    四个子维度：工商基本面 25% + 经营活跃度 25% + 财务健康度 25% + 司法红线 25%
    红线触发 → 整个D3归零
    """
    if redline_result is None:
        redline_result = data.get("_redline_result", {})
    template = _load_template(industry)
    d3_cfg = template["dimension_3"]["sub_dimensions"]
    details = {}

    # ── 工商基本面（25%）──
    biz_scores = {}
    for ind in d3_cfg["工商基本面"]["indicators"]:
        ind_data = data.get(ind["id"], {})
        cv = ind_data.get("company_value")
        direction = ind.get("direction", "higher_better")

        if ind.get("benchmark_method") == "direct":
            # 实缴比例、成立年限等 → 直接映射
            if ind["id"] == "d3_paid_capital_ratio":
                score = score_direct_indicator(cv, 100, 0, "higher_better")
            elif ind["id"] == "d3_establishment_years":
                score = score_direct_indicator(cv, 20, 0, "higher_better")
            else:
                score = score_direct_indicator(cv, 100, 0, "higher_better")
        else:
            bv = ind_data.get("benchmark_value")
            score = score_ratio_indicator(cv, bv, direction, ind["id"])

        biz_scores[ind["id"]] = score
        details[ind["id"]] = {"name": ind["name"], "company_value": cv, "benchmark_value": ind_data.get("benchmark_value"), "score": score}

    biz_avg = _compose_sub_dimension(biz_scores)

    # ── 经营活跃度（25%）──
    ops_scores = {}
    for ind in d3_cfg["经营活跃度"]["indicators"]:
        ind_data = data.get(ind["id"], {})
        if ind.get("direction") == "discrete":
            score = score_discrete_indicator(ind_data.get("company_value"), ind.get("lookup", {}))
            # 连续A级加成
            bonus_years = ind_data.get("consecutive_a_years", 0)
            if bonus_years >= 5 and score is not None:
                score = min(100, score + min(bonus_years * 0.5, 10))
        else:
            cv = ind_data.get("company_value")
            bv = ind_data.get("benchmark_value")
            score = score_ratio_indicator(cv, bv, ind.get("direction", "higher_better"), ind["id"])
        ops_scores[ind["id"]] = score
        details[ind["id"]] = {"name": ind["name"], "company_value": ind_data.get("company_value"), "score": score}

    ops_avg = _compose_sub_dimension(ops_scores)

    # ── 财务健康度（25%）──
    if is_listed:
        fin_scores = {}
        for ind in d3_cfg["财务健康度"].get("indicators_listed", []):
            ind_data = data.get(ind["id"], {})
            cv = ind_data.get("company_value")
            bv = ind_data.get("benchmark_value")
            direction = ind.get("direction", "higher_better")

            if direction == "sweet_spot":
                ss = ind.get("sweet_spot", {"min": 40, "max": 60})
                score = score_sweet_spot_indicator(cv, ss["min"], ss["max"])
            else:
                score = score_ratio_indicator(cv, bv, direction, ind["id"])

            fin_scores[ind["id"]] = score
            details[ind["id"]] = {"name": ind["name"], "company_value": cv, "benchmark_value": bv, "score": score}

        fin_avg = _safe_mean(
            [fin_scores.get("d3_revenue"), fin_scores.get("d3_net_profit"),
             fin_scores.get("d3_debt_ratio"), fin_scores.get("d3_operating_cashflow"),
             fin_scores.get("d3_guarantee_ratio")],
            [0.2, 0.2, 0.2, 0.2, 0.2]
        )
    else:
        # 非上市：代理指标 × 0.85
        proxy = data.get("d3_financial_proxy", {})
        p_tax = proxy.get("tax_score") or score_ratio_indicator(
            data.get("d3_proxy_tax", {}).get("company_value"),
            data.get("d3_proxy_tax", {}).get("benchmark_value"),
            "higher_better", "d3_proxy_tax"
        )
        p_insured = proxy.get("insured_score") or score_ratio_indicator(
            data.get("d3_proxy_insured", {}).get("company_value"),
            data.get("d3_proxy_insured", {}).get("benchmark_value"),
            "higher_better", "d3_proxy_insured"
        )
        p_bidding = proxy.get("bidding_score") or score_ratio_indicator(
            data.get("d3_proxy_bidding", {}).get("company_value"),
            data.get("d3_proxy_bidding", {}).get("benchmark_value"),
            "higher_better", "d3_proxy_bidding"
        )
        fin_avg = _safe_mean([p_tax, p_insured, p_bidding], [0.4, 0.3, 0.3])
        if fin_avg is not None:
            fin_avg *= 0.85  # 非上市降权
        details["d3_financial_proxy"] = {"name": "财务健康度(非上市代理)", "score": fin_avg}

    # ── 司法信用红线（25%）──
    # redline_result 由函数参数传入（run_full_assessment 中 check_redlines 的结果）
    if redline_result.get("triggered"):
        judicial_score = 0.0
    elif redline_result.get("all_clear"):
        if is_listed:
            judicial_score = 100.0
        else:
            judicial_score = 85.0  # 非上市满分85
    else:
        judicial_score = None  # 验证不完整

    details["redline"] = {"name": "司法红线", "triggered": redline_result.get("triggered", False),
                          "all_clear": redline_result.get("all_clear", False), "score": judicial_score}

    # ── 合成 ──
    # 红线触发 → 整个D3归零（一票否决）
    if redline_result.get("triggered"):
        d3_score = 0.0
    else:
        d3_score = _safe_mean([biz_avg, ops_avg, fin_avg, judicial_score], [25, 25, 25, 25])

    return {
        "score": round(d3_score, 1) if d3_score is not None else None,
        "redline_triggered": redline_result.get("triggered", False),
        "sub_scores": {
            "工商基本面": round(biz_avg, 1) if biz_avg else None,
            "经营活跃度": round(ops_avg, 1) if ops_avg else None,
            "财务健康度": round(fin_avg, 1) if fin_avg else None,
            "司法红线": judicial_score
        },
        "details": details
    }


def compute_dimension_4(data: dict, industry: str) -> dict:
    """
    D4 经销商体系健康度（30%）

    三个子维度 + 关联自融排查
    """
    details = {}

    # ── 规模结构（25%）──
    scale_scores = {}
    for key in ["d4_dealer_count", "d4_channel_levels", "d4_region_coverage"]:
        ind_data = data.get(key, {})
        cv = ind_data.get("company_value")
        bv = ind_data.get("benchmark_value")
        score = score_ratio_indicator(cv, bv, "higher_better", key)
        scale_scores[key] = score
        details[key] = {"name": ind_data.get("name", key), "company_value": cv, "score": score}

    scale_avg = _compose_sub_dimension(scale_scores)

    # ── 体系健康（40%）──
    health_scores = {}
    for key in ["d4_abnormal_ratio", "d4_median_establishment_years", "d4_median_insured"]:
        ind_data = data.get(key, {})
        cv = ind_data.get("company_value")
        bv = ind_data.get("benchmark_value")
        direction = "lower_better" if key == "d4_abnormal_ratio" else "higher_better"
        score = score_ratio_indicator(cv, bv, direction, key)
        health_scores[key] = score
        details[key] = {"name": ind_data.get("name", key), "company_value": cv, "score": score}

    health_avg = _compose_sub_dimension(health_scores)

    # ── 集中度（35%）──
    concentration_scores = {}
    for key in ["d4_top1_dealer_ratio", "d4_top3_dealer_ratio", "d4_single_region_ratio"]:
        ind_data = data.get(key, {})
        cv = ind_data.get("company_value")
        bv = ind_data.get("benchmark_value")
        score = score_ratio_indicator(cv, bv, "lower_better", key)
        concentration_scores[key] = score
        details[key] = {"name": ind_data.get("name", key), "company_value": cv, "score": score}

    concentration_avg = _compose_sub_dimension(concentration_scores)

    # ── 关联自融排查 ──
    related_party = data.get("_related_party_result", {})
    rp_penalty = 0
    rp_checks = related_party.get("checks", {})
    for check_name, triggered in rp_checks.items():
        if triggered:
            if check_name in ["equity_penetration", "controller_overlap"]:
                rp_penalty += 20
            else:
                rp_penalty += 15

    # 股权穿透 + 实控人同时触发 → 额外扣30
    if rp_checks.get("equity_penetration") and rp_checks.get("controller_overlap"):
        rp_penalty += 30

    # ── 合成 ──
    d4_score = _safe_mean([scale_avg, health_avg, concentration_avg], [25, 40, 35])
    if d4_score is not None:
        d4_score = max(0, d4_score - rp_penalty)

    return {
        "score": round(d4_score, 1) if d4_score else None,
        "related_party_penalty": rp_penalty,
        "sub_scores": {
            "规模结构": round(scale_avg, 1) if scale_avg else None,
            "体系健康": round(health_avg, 1) if health_avg else None,
            "集中度": round(concentration_avg, 1) if concentration_avg else None,
            "关联自融扣分": -rp_penalty
        },
        "details": details
    }


# ═══════════════════════════════════════════════════════════════
# 第4层：红线检查
# ═══════════════════════════════════════════════════════════════

def check_redlines(redline_data: dict, is_listed: bool) -> dict:
    """
    6条红线逐项检查（R001-R006）。

    redline_data格式:
    {
      "R001_失信": {"triggered": false, "sources": ["qcc", "中国执行信息公开网"], "tier1_count": 1},
      ...
    }

    返回:
      {triggered: bool, all_clear: bool, triggered_lines: [str], insufficient: [str]}
    """
    triggered_lines = []
    insufficient = []
    all_checked = True

    for rule_key, check in redline_data.items():
        if not isinstance(check, dict):
            continue
        if check.get("triggered"):
            triggered_lines.append(rule_key)
        elif not check.get("verified"):
            insufficient.append(rule_key)
            all_checked = False

    return {
        "triggered": len(triggered_lines) > 0,
        "all_clear": len(triggered_lines) == 0 and all_checked,
        "triggered_lines": triggered_lines,
        "insufficient": insufficient
    }


# ═══════════════════════════════════════════════════════════════
# 第5层：综合评分 + 评级映射
# ═══════════════════════════════════════════════════════════════

def compute_total(dim_scores: Dict[str, Optional[float]], weights: dict = None) -> dict:
    """
    加权总分 + 权重重新分配（数据缺失时）。

    权重:
      D1: 15%, D2: 15%, D3: 40%, D4: 30%

    缺失维度 → 权重按比例分给剩余维度。
    """
    if weights is None:
        weights = {"D1": 15, "D2": 15, "D3": 40, "D4": 30}

    available = {k: v for k, v in dim_scores.items() if v is not None}
    if not available:
        return {"total_score": None, "rating": "无法评级", "rating_label": "数据不足",
                "dim_scores": dim_scores, "weight_redistribution": "无可用维度"}

    # 检查 D3 是否为0（红线触发）
    if dim_scores.get("D3") == 0.0:
        return {"total_score": 0.0, "rating": "D", "rating_label": "不建议准入（红线一票否决）",
                "dim_scores": dim_scores, "redline_veto": True}

    # 权重重分配：缺失维度的权重按比例分给有数据的维度
    missing_weight = sum(w for dim, w in weights.items() if dim not in available)
    total_available_weight = sum(w for dim, w in weights.items() if dim in available)

    total = 0.0
    effective_weights = {}
    for dim in available:
        original_w = weights[dim]
        redistributed_w = original_w + (original_w / total_available_weight) * missing_weight if total_available_weight > 0 else original_w
        effective_weights[dim] = redistributed_w
        total += available[dim] * redistributed_w / 100

    total = round(total, 1)

    # 评级映射
    rating_map = [("A", 80, "优先准入"), ("B", 70, "建议准入"), ("C", 60, "有条件准入"), ("D", 0, "不建议准入")]
    rating, label = "D", "不建议准入"
    for r, threshold, lbl in rating_map:
        if total >= threshold:
            rating, label = r, lbl
            break

    return {
        "total_score": total,
        "rating": rating,
        "rating_label": label,
        "dim_scores": dim_scores,
        "effective_weights": effective_weights,
        "weight_redistribution": f"缺失维度权重已重分配" if missing_weight > 0 else "无缺失"
    }


# ═══════════════════════════════════════════════════════════════
# 第6层：完整评估入口
# ═══════════════════════════════════════════════════════════════

def run_full_assessment(data: dict) -> dict:
    """
    完整评估入口。

    data 结构:
    {
      "company": {
        "name": "格力电器",
        "is_listed": true,
        "industry": "家用电器",
        "stock_code": "000651.SZ"
      },
      "d1": { 指标id: {company_value, benchmark_value, benchmark_vintage} },
      "d2": { ... },
      "d3": { ... },
      "d4": { ... },
      "redline": { 红线id: {triggered, verified, sources} },
      "_volume_direction": "down",
      "_price_direction": "stable",
      "_external_adjustment": 5,
      "_related_party_result": {checks: {...}},
      "_no_authorization": false,
      "_counterfeit_brand": false
    }

    返回:
    {
      "company_name": str,
      "industry": str,
      "is_listed": bool,
      "dimension_scores": {"D1": float, "D2": float, "D3": float, "D4": float},
      "total_score": float,
      "rating": "A/B/C/D",
      "rating_label": str,
      "redline_triggered": bool,
      "data_completeness": {...},
      "vintage_summary": {...}
    }
    """
    company = data.get("company", {})
    name = company.get("name", "未知")
    industry = company.get("industry", "家用电器")
    is_listed = company.get("is_listed", True)

    # 红线检查（在D3之前，因为红线影响D3）
    redline_result = check_redlines(data.get("redline", {}), is_listed)

    # 四维评分
    d1 = compute_dimension_1(data.get("d1", {}), industry, is_listed)
    d2 = compute_dimension_2(data.get("d2", {}), industry, is_listed)
    d3 = compute_dimension_3(data.get("d3", {}), industry, is_listed, redline_result)
    d4 = compute_dimension_4(data.get("d4", {}), industry)

    dim_scores = {"D1": d1["score"], "D2": d2["score"], "D3": d3["score"], "D4": d4["score"]}

    # 综合评分
    total_result = compute_total(dim_scores)

    # 数据完整度
    data_completeness = {
        "D1": _dimension_completeness(data.get("d1", {})),
        "D2": _dimension_completeness(data.get("d2", {})),
        "D3": _dimension_completeness(data.get("d3", {})),
        "D4": _dimension_completeness(data.get("d4", {}))
    }

    # 数据年份汇总
    vintage_summary = _collect_vintages(data)

    return {
        "company_name": name,
        "industry": industry,
        "is_listed": is_listed,
        "stock_code": company.get("stock_code", ""),
        "dimension_scores": dim_scores,
        "dimension_details": {"D1": d1, "D2": d2, "D3": d3, "D4": d4},
        "total_score": total_result["total_score"],
        "rating": total_result["rating"],
        "rating_label": total_result["rating_label"],
        "redline_triggered": redline_result["triggered"],
        "redline_details": redline_result,
        "data_completeness": data_completeness,
        "vintage_summary": vintage_summary,
        "effective_weights": total_result.get("effective_weights", {})
    }


def _dimension_completeness(dim_data: dict) -> float:
    """计算维度数据完整度（0-1）"""
    if not dim_data:
        return 0.0
    total = len(dim_data)
    available = sum(1 for v in dim_data.values()
                    if isinstance(v, dict) and v.get("company_value") is not None)
    return available / total if total > 0 else 0.0


def _collect_vintages(data: dict) -> dict:
    """收集各指标的数据年份"""
    vintages = set()
    for dim_key in ["d1", "d2", "d3", "d4"]:
        dim_data = data.get(dim_key, {})
        for k, v in dim_data.items():
            if isinstance(v, dict) and v.get("benchmark_vintage"):
                vintages.add(v["benchmark_vintage"])
    return {"vintages": sorted(vintages), "note": "公司数据年份：2025年报/2026Q1，行业基准年份见各指标标注"}


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("规则引擎 v1.0 — 比率打分测试")
    print("=" * 60)

    # ── 测试1：格力电器（上市，家电行业）──
    print("\n[TEST 1] 格力电器（上市，家电行业）")

    gree_data = {
        "company": {"name": "格力电器", "is_listed": True, "industry": "家用电器", "stock_code": "000651.SZ"},
        "d1": {
            "d1_revenue_growth":     {"company_value": -9.89, "benchmark_value": 6.4, "benchmark_vintage": "2025年度"},
            "d1_roe":                {"company_value": 20.3,  "benchmark_value": 3.2, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_profit_margin":      {"company_value": 30.0,  "benchmark_value": 2.0, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_inventory_turnover": {"company_value": 4.5,   "benchmark_value": 6.6, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_asset_return":       {"company_value": 8.0,   "benchmark_value": 2.3, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_debt_ratio":         {"company_value": 61.7,  "benchmark_value": 59.3, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_aircon_shipment":    {"company_value": 75.0,  "benchmark_value": 80.0, "benchmark_vintage": "2025年度"},
            "d1_raw_material_price": {"company_value": 50.0,  "benchmark_value": 40.0, "benchmark_vintage": "2025年度"},
            "d1_retail_sales":       {"company_value": 8.0,   "benchmark_value": 5.0, "benchmark_vintage": "2025年度"},
            "d1_excess_return":      {"company_value": 5.0,   "benchmark_value": 0.0, "benchmark_vintage": "2025年度"},
            "d1_pe_percentile":      {"company_value": 10.0,  "benchmark_value": 50.0, "benchmark_vintage": "2025年度"},
            "d1_analyst_sentiment":  {"company_value": "中性偏正面", "benchmark_value": None},
        },
        "d2": {
            "d2_brand_tier": "A",
            "d2_market_share": {"rank": "2/88", "score": 85.0},
            "d2_gross_margin":     {"company_value": 30.0, "benchmark_value": 2.0, "benchmark_vintage": "2024年度(全行业均值)"},
            "d2_cashflow_ratio":   {"company_value": 0.272, "benchmark_value": 0.08, "benchmark_vintage": "2024年度(全行业均值)"},
            "d2_patent_count":     {"company_value": 126247, "benchmark_value": None},
            "d2_public_sentiment": {"company_value": "正面为主"},
            "d2_rd_intensity":     {"company_value": 3.5, "benchmark_value": 2.5, "benchmark_vintage": "2024年度(全行业均值)"},
        },
        "d3": {
            "d3_registered_capital":   {"company_value": 56.01, "benchmark_value": 8.0},
            "d3_paid_capital_ratio":   {"company_value": 100.0},
            "d3_establishment_years":  {"company_value": 36.0},
            "d3_insured_count":        {"company_value": 19225, "benchmark_value": 500},
            "d3_bidding_count":        {"company_value": 294, "benchmark_value": 30},
            "d3_tax_rating":           {"company_value": "A", "consecutive_a_years": 12},
            "d3_patent_count":         {"company_value": 126247, "benchmark_value": 1000},
            "d3_revenue":              {"company_value": 1704.47, "unit": "亿"},
            "d3_net_profit":           {"company_value": 290.03, "unit": "亿"},
            "d3_debt_ratio":           {"company_value": 61.73},
            "d3_operating_cashflow":   {"company_value": 463.83, "unit": "亿"},
            "d3_guarantee_ratio":      {"company_value": 5.0, "benchmark_value": 10.0},
        },
        "d4": {
            "d4_dealer_count":              {"company_value": 30.0, "benchmark_value": 50.0},
            "d4_channel_levels":            {"company_value": 3.0, "benchmark_value": 4.0, "direction": "higher_better"},
            "d4_region_coverage":           {"company_value": 30.0, "benchmark_value": 25.0},
            "d4_abnormal_ratio":            {"company_value": 5.0, "benchmark_value": 10.0},
            "d4_median_establishment_years": {"company_value": 8.0, "benchmark_value": 5.0},
            "d4_median_insured":            {"company_value": 30.0, "benchmark_value": 20.0},
            "d4_top1_dealer_ratio":         {"company_value": 13.0, "benchmark_value": 20.0},
            "d4_top3_dealer_ratio":         {"company_value": 30.0, "benchmark_value": 40.0},
            "d4_single_region_ratio":       {"company_value": 3.0, "benchmark_value": 15.0},
        },
        "redline": {
            "R001_失信": {"triggered": False, "verified": True, "sources": ["qcc", "中国执行信息公开网"]},
            "R002_税收违法": {"triggered": False, "verified": True, "sources": ["qcc", "信用中国"]},
            "R003_经营异常": {"triggered": False, "verified": True, "sources": ["qcc", "国家企业信用信息公示系统"]},
            "R004_重大行政处罚": {"triggered": False, "verified": True, "sources": ["qcc", "信用中国"]},
            "R005_假冒伪劣": {"triggered": False, "verified": True, "sources": ["qcc", "中国裁判文书网"]},
            "R006_非法经营": {"triggered": False, "verified": True, "sources": ["qcc", "国家企业信用信息公示系统"]},
        },
        "_volume_direction": "down",
        "_price_direction": "stable",
        "_external_adjustment": 5,
        "_related_party_result": {"checks": {"equity_penetration": False, "controller_overlap": False, "executive_overlap": False, "dealer_cross_hold": False}},
    }

    result = run_full_assessment(gree_data)
    print(f"  公司: {result['company_name']}")
    print(f"  行业: {result['industry']} | 上市: {result['is_listed']}")
    print(f"  四维: D1={result['dimension_scores']['D1']} | D2={result['dimension_scores']['D2']} | D3={result['dimension_scores']['D3']} | D4={result['dimension_scores']['D4']}")
    print(f"  综合: {result['total_score']} → {result['rating']}级 ({result['rating_label']})")
    print(f"  红线: {'触发!' if result['redline_triggered'] else '通过'}")

    # ── 测试2：荣耀（非上市，消费电子行业）──
    print("\n[TEST 2] 荣耀终端（非上市，消费电子）")

    honor_data = {
        "company": {"name": "荣耀终端股份有限公司", "is_listed": False, "industry": "消费电子", "stock_code": ""},
        "d1": {
            "d1_revenue_growth":     {"company_value": 15.0, "benchmark_value": 10.0, "benchmark_vintage": "2025年度"},
            "d1_roe":                {"company_value": 18.0, "benchmark_value": 3.0, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_profit_margin":      {"company_value": 12.0, "benchmark_value": 3.0, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_inventory_turnover": {"company_value": 8.0,  "benchmark_value": 5.0, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_asset_return":       {"company_value": 10.0, "benchmark_value": 3.0, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_debt_ratio":         {"company_value": 45.0, "benchmark_value": 55.0, "benchmark_vintage": "2024年度(全行业均值)"},
            "d1_aircon_shipment":    {"company_value": 90.0, "benchmark_value": 80.0},
            "d1_raw_material_price": {"company_value": 40.0, "benchmark_value": 35.0},
            "d1_retail_sales":       {"company_value": 12.0, "benchmark_value": 8.0},
            "d1_excess_return":      {"company_value": None, "benchmark_value": None},
            "d1_pe_percentile":      {"company_value": None, "benchmark_value": None},
            "d1_analyst_sentiment":  {"company_value": "中性偏正面"},
        },
        "d2": {
            "d2_brand_tier": "A",
            "d2_market_share": {"rank": "", "score": 78.0},
            "d2_proxy": {"revenue_rank_score": 75.0, "tax_score": 70.0, "bidding_score": 80.0},
            "d2_patent_count":     {"company_value": 15000, "benchmark_value": None},
            "d2_public_sentiment": {"company_value": "正面为主"},
            "d2_rd_intensity":     {"company_value": 8.0, "benchmark_value": 5.0},
        },
        "d3": {
            "d3_registered_capital":   {"company_value": 50.0, "benchmark_value": 5.0},
            "d3_paid_capital_ratio":   {"company_value": 100.0},
            "d3_establishment_years":  {"company_value": 12.0},
            "d3_insured_count":        {"company_value": 8000, "benchmark_value": 300},
            "d3_bidding_count":        {"company_value": 150, "benchmark_value": 20},
            "d3_tax_rating":           {"company_value": "A", "consecutive_a_years": 8},
            "d3_patent_count":         {"company_value": 15000, "benchmark_value": 500},
            "d3_financial_proxy": {"tax_score": 82.0, "insured_score": 85.0, "bidding_score": 78.0},
        },
        "d4": {
            "d4_dealer_count":              {"company_value": 200.0, "benchmark_value": 100.0},
            "d4_channel_levels":            {"company_value": 3.0, "benchmark_value": 3.0},
            "d4_region_coverage":           {"company_value": 28.0, "benchmark_value": 20.0},
            "d4_abnormal_ratio":            {"company_value": 3.0, "benchmark_value": 8.0},
            "d4_median_establishment_years": {"company_value": 6.0, "benchmark_value": 4.0},
            "d4_median_insured":            {"company_value": 25.0, "benchmark_value": 15.0},
            "d4_top1_dealer_ratio":         {"company_value": 8.0, "benchmark_value": 15.0},
            "d4_top3_dealer_ratio":         {"company_value": 20.0, "benchmark_value": 30.0},
            "d4_single_region_ratio":       {"company_value": 5.0, "benchmark_value": 20.0},
        },
        "redline": {
            "R001_失信": {"triggered": False, "verified": True, "sources": ["qcc", "中国执行信息公开网"]},
            "R002_税收违法": {"triggered": False, "verified": True, "sources": ["qcc", "信用中国"]},
            "R003_经营异常": {"triggered": False, "verified": True, "sources": ["qcc", "国家企业信用信息公示系统"]},
            "R004_重大行政处罚": {"triggered": False, "verified": True, "sources": ["qcc", "信用中国"]},
            "R005_假冒伪劣": {"triggered": False, "verified": True, "sources": ["qcc", "中国裁判文书网"]},
            "R006_非法经营": {"triggered": False, "verified": True, "sources": ["qcc", "国家企业信用信息公示系统"]},
        },
        "_volume_direction": "up",
        "_price_direction": "up",
        "_external_adjustment": 3,
        "_related_party_result": {"checks": {"equity_penetration": False, "controller_overlap": False, "executive_overlap": False, "dealer_cross_hold": False}},
    }

    result2 = run_full_assessment(honor_data)
    print(f"  公司: {result2['company_name']}")
    print(f"  行业: {result2['industry']} | 上市: {result2['is_listed']}")
    print(f"  四维: D1={result2['dimension_scores']['D1']} | D2={result2['dimension_scores']['D2']} | D3={result2['dimension_scores']['D3']} | D4={result2['dimension_scores']['D4']}")
    print(f"  综合: {result2['total_score']} → {result2['rating']}级 ({result2['rating_label']})")
    print(f"  红线: {'触发!' if result2['redline_triggered'] else '通过'}")

    # ── 测试3：远辰（红线触发）──
    print("\n[TEST 3] 远辰精密化工（红线案例）")

    yuanchen_data = {
        "company": {"name": "远辰精密化工有限公司", "is_listed": False, "industry": "家用电器", "stock_code": ""},
        "d1": {
            "d1_revenue_growth":     {"company_value": 5.0, "benchmark_value": 6.4},
            "d1_roe":                {"company_value": 8.0, "benchmark_value": 3.2},
            "d1_profit_margin":      {"company_value": 10.0, "benchmark_value": 2.0},
            "d1_inventory_turnover": {"company_value": 5.0, "benchmark_value": 6.6},
            "d1_asset_return":       {"company_value": 4.0, "benchmark_value": 2.3},
            "d1_debt_ratio":         {"company_value": 70.0, "benchmark_value": 59.3},
            "d1_aircon_shipment":    {"company_value": 70.0, "benchmark_value": 80.0},
            "d1_raw_material_price": {"company_value": 55.0, "benchmark_value": 40.0},
            "d1_retail_sales":       {"company_value": 4.0, "benchmark_value": 5.0},
            "d1_excess_return":      {"company_value": None, "benchmark_value": None},
            "d1_pe_percentile":      {"company_value": None, "benchmark_value": None},
            "d1_analyst_sentiment":  {"company_value": "中性偏负面"},
        },
        "d2": {
            "d2_brand_tier": "B",
            "d2_market_share": {"rank": "", "score": 50.0},
            "d2_proxy": {"revenue_rank_score": 45.0, "tax_score": 40.0, "bidding_score": 50.0},
            "d2_patent_count":     {"company_value": 500, "benchmark_value": None},
            "d2_public_sentiment": {"company_value": "中性"},
            "d2_rd_intensity":     {"company_value": 2.0, "benchmark_value": 2.5},
        },
        "d3": {
            "d3_registered_capital":   {"company_value": 1.0, "benchmark_value": 8.0},
            "d3_paid_capital_ratio":   {"company_value": 50.0},
            "d3_establishment_years":  {"company_value": 8.0},
            "d3_insured_count":        {"company_value": 80, "benchmark_value": 500},
            "d3_bidding_count":        {"company_value": 10, "benchmark_value": 30},
            "d3_tax_rating":           {"company_value": "B"},
            "d3_patent_count":         {"company_value": 50, "benchmark_value": 1000},
            "d3_financial_proxy": {"tax_score": 35.0, "insured_score": 30.0, "bidding_score": 25.0},
        },
        "d4": {
            "d4_dealer_count":              {"company_value": 5.0, "benchmark_value": 50.0},
            "d4_channel_levels":            {"company_value": 1.0, "benchmark_value": 4.0},
            "d4_region_coverage":           {"company_value": 2.0, "benchmark_value": 25.0},
            "d4_abnormal_ratio":            {"company_value": 25.0, "benchmark_value": 10.0},
            "d4_median_establishment_years": {"company_value": 3.0, "benchmark_value": 5.0},
            "d4_median_insured":            {"company_value": 5.0, "benchmark_value": 20.0},
            "d4_top1_dealer_ratio":         {"company_value": 60.0, "benchmark_value": 20.0},
            "d4_top3_dealer_ratio":         {"company_value": 90.0, "benchmark_value": 40.0},
            "d4_single_region_ratio":       {"company_value": 80.0, "benchmark_value": 15.0},
        },
        "redline": {
            "R001_失信": {"triggered": False, "verified": True, "sources": ["qcc", "中国执行信息公开网"]},
            "R002_税收违法": {"triggered": True, "verified": True, "sources": ["qcc", "信用中国"]},
            "R003_经营异常": {"triggered": False, "verified": True, "sources": ["qcc", "国家企业信用信息公示系统"]},
            "R004_重大行政处罚": {"triggered": False, "verified": True, "sources": ["qcc", "信用中国"]},
            "R005_假冒伪劣": {"triggered": False, "verified": True, "sources": ["qcc", "中国裁判文书网"]},
            "R006_非法经营": {"triggered": False, "verified": True, "sources": ["qcc", "国家企业信用信息公示系统"]},
        },
        "_volume_direction": "down",
        "_price_direction": "up",
        "_external_adjustment": 0,
        "_related_party_result": {"checks": {"equity_penetration": False, "controller_overlap": False, "executive_overlap": False, "dealer_cross_hold": False}},
    }

    result3 = run_full_assessment(yuanchen_data)
    print(f"  公司: {result3['company_name']}")
    print(f"  红线: {'触发! ' + str(result3['redline_details']['triggered_lines']) if result3['redline_triggered'] else '通过'}")
    print(f"  D3: {result3['dimension_scores']['D3']} (红线触发归零)")
    print(f"  综合: {result3['total_score']} → {result3['rating']}级 ({result3['rating_label']})")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
