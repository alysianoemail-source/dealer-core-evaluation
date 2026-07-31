"""
Vercel Serverless Function — 经销商核企评分 API

用法：
  POST /api/evaluate
  {
    "company_name": "格力电器"            // 演示模式：按名称查内置数据
    // 或传入完整引擎输入数据（参见 rule_engine.py run_full_assessment 的 data 参数）
  }

返回：
  {
    "company_name": "格力电器",
    "dimension_scores": {"D1": 87, "D2": 82, ...},
    "total_score": 85,
    "rating": "A",
    "redline_triggered": false,
    ...
  }
"""

import json
import sys
import os
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── 把项目根加入 Python 路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rule_engine import run_full_assessment

# ── 加载演示案例数据 ──
DEMO_DATA_PATH = Path(__file__).resolve().parent / "demo_cases.json"
_demo_data = None

def _load_demo_cases():
    global _demo_data
    if _demo_data is None:
        if DEMO_DATA_PATH.exists():
            with open(DEMO_DATA_PATH, "r", encoding="utf-8") as f:
                _demo_data = json.load(f)
        else:
            _demo_data = {}
    return _demo_data


app = Flask(__name__)
CORS(app)  # 允许前端跨域请求


@app.route("/")
def index():
    """网站首页：返回前端演示页面（部署后访问根地址直接看到界面）"""
    return app.send_static_file("index.html")


@app.route("/api/evaluate", methods=["POST", "OPTIONS"])
def evaluate():
    """评分 API"""
    if request.method == "OPTIONS":
        return _cors_response()

    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"error": "请求体为空"}), 400

        # ── 模式1：传入 company_name，从演示数据查找 ──
        if "company_name" in body and not ("d1" in body or "company" in body):
            company_name = body["company_name"]
            demo = _load_demo_cases()
            if company_name in demo:
                input_data = demo[company_name]
            else:
                # 尝试模糊匹配
                matched = None
                for key in demo:
                    if company_name in key or key in company_name:
                        matched = key
                        break
                if matched:
                    input_data = demo[matched]
                else:
                    return jsonify({
                        "error": f"未找到企业「{company_name}」的演示数据",
                        "hint": "可用企业：" + "、".join(demo.keys())
                    }), 404

        # ── 模式2：直接传入完整引擎输入数据 ──
        else:
            input_data = body

        # ── 执行评分引擎 ──
        result = run_full_assessment(input_data)

        # 补充经销商名称（如果有）
        dealer = input_data.get("dealer", {}).get("name", "")
        if dealer:
            result["dealer_name"] = dealer

        # 补充是否有展示数据的标记（区别于"未找到案例"）
        result["_demo_mode"] = "company_name" in body and not ("d1" in body)

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "error": f"评分引擎异常: {str(e)}",
            "type": type(e).__name__
        }), 500


def _cors_response():
    resp = jsonify({"ok": True})
    resp.headers.add("Access-Control-Allow-Origin", "*")
    resp.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
    resp.headers.add("Access-Control-Allow-Headers", "Content-Type")
    return resp


# ── Vercel 需要这个 ──
handler = app
