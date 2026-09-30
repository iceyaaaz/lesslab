"""仅供旧业务单元测试使用；test_auth.py 不绕过登录依赖。"""
from pathlib import Path
import sys

root = str(Path(__file__).resolve().parents[1])
if root not in sys.path:
    sys.path.insert(0, root)

from security import require_user


def authorize(app):
    app.dependency_overrides[require_user] = lambda: {"id": 1, "username": "owner"}
