from pathlib import Path
import os

import httpx
from dotenv import dotenv_values


def main():
    # 读取配置，但不打印密钥。
    config = dotenv_values(Path(__file__).with_name(".env"))
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        if name in os.environ:
            config[name] = os.environ[name]

    api_key = (config.get("DEEPSEEK_API_KEY") or "").strip()
    base_url = (
        config.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    ).rstrip("/")
    model = config.get("DEEPSEEK_MODEL") or "deepseek-flash"

    if not api_key:
        print("未找到密钥，请检查 .env 中的 DEEPSEEK_API_KEY。")
        return 1

    # 每次运行只发送一次请求，不自动重试。
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "请只回复四个字：连接成功",
                    }
                ],
                "thinking": {"type": "disabled"},
                "max_tokens": 64,
                "stream": False,
            },
            timeout=30.0,
        )
    except httpx.RequestError as error:
        print(f"网络请求失败：{type(error).__name__}")
        print("请检查网络连接，先不要连续重复运行。")
        return 1

    if response.status_code != 200:
        explanations = {
            400: "请求格式错误，请检查地址、模型和请求参数。",
            401: "认证失败，请检查 API Key。",
            402: "API 账户余额不足，请检查开放平台余额。",
            422: "请求参数不符合要求。",
            429: "请求速率达到上限，请稍后再试。",
            500: "模型服务内部错误。",
            503: "模型服务繁忙。",
        }

        print(f"调用失败，HTTP 状态码：{response.status_code}")
        print(explanations.get(response.status_code, "请根据状态码排查。"))
        return 1

    try:
        data = response.json()
        reply = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}

        if not isinstance(reply, str) or not reply.strip():
            print("请求成功，但没有收到文字回复。")
            return 1

        print("模型回复：", reply.strip())
        print("输入 token：", usage.get("prompt_tokens", "未返回"))
        print("输出 token：", usage.get("completion_tokens", "未返回"))
        return 0

    except (ValueError, KeyError, IndexError, TypeError):
        print("收到的响应格式异常，请先保留现场排查。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
