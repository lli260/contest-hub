# -*- coding: utf-8 -*-
"""Contest Hub 运行入口。

启动开发服务器::

    uv run python app.py

也可直接作为 WSGI 应用对象使用（``from app import app``），例如
``waitress-serve --call app:app``。
"""
import os

from contesthub import create_app

#: WSGI 应用对象（gunicorn / waitress 等直接引用）
app = create_app()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def _int_env(name, default):
    """读取整型环境变量，非法值或非正数一律回退到默认值。"""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def main():
    host = os.environ.get("CONTESTHUB_HOST") or DEFAULT_HOST
    port = _int_env("PORT", DEFAULT_PORT)
    print(f"[OK] Contest Hub 已启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
