"""测试包初始化：确保测试模式环境变量最早设置。"""

from __future__ import annotations

import os

os.environ.setdefault("TESTING", "1")
