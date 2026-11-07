# -*- coding: utf-8 -*-
"""pytest 公共夹具。

注意：这里**不用** pytest 自带的 ``tmp_path``。某些 Windows 环境下
pytest 清理临时目录时会调用 ``os.scandir`` 枚举目录，而系统权限会拒绝
这类枚举（与被测代码无关），导致所有用到 ``tmp_path`` 的测试在 setup
阶段就报 Access Denied。下面用一个只用 ``mkdir`` 的替代实现。
"""
import os
import sys
import uuid

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
# 让测试目录本身可以被 ``import conftest`` / 直接跑单文件
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contesthub import create_app  # noqa: E402
from contesthub import sync as sync_mod  # noqa: E402
from contesthub.db import BASE_SCHEMA  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_TEST_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp")
os.makedirs(_TEST_ROOT, exist_ok=True)


def read_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class TempDir:
    """极简临时目录：只 mkdir，不枚举、不清理。"""

    def __init__(self):
        root = os.environ.get("CONTESTHUB_TEST_TMP") or _TEST_ROOT
        self._root = os.path.join(root, "t_" + uuid.uuid4().hex[:10])
        os.makedirs(self._root, exist_ok=True)

    def __truediv__(self, name):
        return os.path.join(self._root, name)

    def __str__(self):
        return self._root


@pytest.fixture()
def tmp_path():
    """覆盖 pytest 的 tmp_path（见模块开头的说明）。"""
    return TempDir()


@pytest.fixture()
def app(tmp_path):
    # 测试绝不启动后台线程
    sync_mod._bg_started = True
    sync_mod.clear_cache()
    application = create_app({
        "DATABASE": str(tmp_path / "test.db"),
        "DISABLE_BG_SYNC": True,
        "TESTING": True,
    })
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    from contesthub.db import connect
    conn = connect(app.config["DATABASE"])
    yield conn
    conn.close()


@pytest.fixture()
def memory_db():
    """内存库：直接建表，不经过 seed，便于精确断言去重行为。"""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(BASE_SCHEMA)
    return conn


class FakeResponse:
    def __init__(self, body=b"", status=200, encoding="utf-8", content_type=""):
        self.content = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.status_code = status
        self.encoding = encoding
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} error")

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", "replace")

    def json(self):
        import json
        return json.loads(self.text)


@pytest.fixture()
def fake_transport(monkeypatch):
    """把 sources.base.transport 换成可控的假响应，测试完全离线。

    用法::

        routes, FakeResponse = fake_transport
        routes["codeforces.com"] = FakeResponse('{"status":"OK","result":[]}')
    """
    from contesthub.sources import base

    routes = {}

    def transport(method, url, **kwargs):
        for matcher, resp in routes.items():
            if matcher in url:
                if callable(resp):
                    return resp(method, url, **kwargs)
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"未预期的请求：{method} {url}")

    monkeypatch.setattr(base, "transport", transport)
    sync_mod.clear_cache()
    return routes, FakeResponse
