#!/usr/bin/env python3
"""
Zephyr AI Desktop — ModelScope API 连通性测试脚本
===================================================
用途：容器启动后验证 ModelScope API 推理端点是否可用。
运行：python3 modelscope-api-test.py
依赖：requests（pip install requests）

维护者：极客-AI模型通
"""

import os
import sys
import json
import requests


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
API_BASE_URL = "https://api-inference.modelscope.cn/v1"
API_KEY = os.environ.get("MODELSCOPE_API_KEY", "")

# 测试用的模型（Qwen3-235B，免费 2000 次/日）
TEST_MODELS = [
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "Qwen/Qwen3-235B-A22B",
    "Qwen/Qwen3-Coder-480B-A35B-Instruct",
]

TEST_PROMPT = "你好，请用一句话介绍你自己。"


# ---------------------------------------------------------------------------
# 测试函数
# ---------------------------------------------------------------------------
def test_chat_completions(model_id: str) -> dict:
    """测试 OpenAI 兼容的 /v1/chat/completions 端点"""
    url = f"{API_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [
            {"role": "user", "content": TEST_PROMPT}
        ],
        "max_tokens": 100,
        "temperature": 0.7,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "status": "ok",
                "model": model_id,
                "response": content[:200],
                "usage": data.get("usage", {}),
            }
        else:
            return {
                "status": "error",
                "model": model_id,
                "http_code": resp.status_code,
                "error": resp.text[:300],
            }
    except Exception as e:
        return {
            "status": "exception",
            "model": model_id,
            "error": str(e),
        }


def test_models_list() -> dict:
    """测试 /v1/models 端点，列出可用模型"""
    url = f"{API_BASE_URL}/models"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", [])]
            return {"status": "ok", "available_models": models[:20]}
        else:
            return {"status": "error", "http_code": resp.status_code, "error": resp.text[:300]}
    except Exception as e:
        return {"status": "exception", "error": str(e)}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Zephyr AI Desktop — ModelScope API 连通性测试")
    print("=" * 60)

    # 1. 检查 API Key
    if not API_KEY:
        print("[FAIL] MODELSCOPE_API_KEY 环境变量未设置")
        print("       请在 ModelScope Secrets 中配置 MODELSCOPE_API_KEY=ms-xxxxxxxx")
        sys.exit(1)

    print(f"\n[OK] API Key 已配置: [REDACTED]（长度 {len(API_KEY)} 字符）")
    print(f"[INFO] API Base URL: {API_BASE_URL}")

    # 2. 测试模型列表
    print("\n--- 测试 /v1/models 端点 ---")
    models_result = test_models_list()
    if models_result["status"] == "ok":
        print(f"[OK] 可用模型 ({len(models_result['available_models'])} 个):")
        for m in models_result["available_models"][:10]:
            print(f"     - {m}")
        if len(models_result["available_models"]) > 10:
            print(f"     ... 共 {len(models_result['available_models'])} 个")
    else:
        print(f"[WARN] /v1/models 端点不可用: {models_result}")

    # 3. 测试 chat completions
    print("\n--- 测试 /v1/chat/completions 端点 ---")
    success = False
    for model_id in TEST_MODELS:
        print(f"\n  测试模型: {model_id}")
        result = test_chat_completions(model_id)

        if result["status"] == "ok":
            print(f"  [OK] 响应: {result['response']}")
            print(f"       Token 使用: {result.get('usage', {})}")
            print(f"\n  >>> 推荐模型 ID: {model_id} <<<")
            success = True
            break
        elif result["status"] == "error":
            print(f"  [SKIP] HTTP {result['http_code']}: {result['error']}")
        else:
            print(f"  [SKIP] 异常: {result['error']}")

    print("\n" + "=" * 60)
    if success:
        print("[PASS] ModelScope API 推理可用，Open WebUI 可配置 API 后端")
    else:
        print("[WARN] 无可用模型（可能当日额度已用完），本地 llama.cpp 仍可用")
        print("       本地模型: http://127.0.0.1:8081/v1 (qwen3-8b-local)")
    print("=" * 60)


if __name__ == "__main__":
    main()
