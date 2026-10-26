"""toolschema —— 自检测试。

比对工具描述、参数模式与实现行为，标出描述与实现不符的地方。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import toolschema  # noqa: E402


class TestToolSchema(unittest.TestCase):
    def setUp(self):
        self.src = (
            "def calc(a, b):\n"
            "    # 差值说明\n"
            "    return 1.0\n"
        )
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                              encoding="utf-8")
        self.tmp.write(self.src)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_return_type_mismatch_detected(self):
        spec = {"description": "返回列表", "parameters": {"properties": {}}}
        src = toolschema.analyze_source(self.tmp.name)
        r = toolschema.check(spec, src)
        kinds = [f["kind"] for f in r["findings"]]
        self.assertIn("return_type_mismatch", kinds)

    def test_matching_description_passes(self):
        spec = {"description": "返回数字", "parameters": {"properties": {}}}
        src = toolschema.analyze_source(self.tmp.name)
        r = toolschema.check(spec, src)
        kinds = [f["kind"] for f in r["findings"]]
        self.assertNotIn("return_type_mismatch", kinds)

    def test_required_param_missing_detected(self):
        spec = {"description": "计算", "parameters": {
            "required": ["a", "b", "c"], "properties": {"a": {}, "b": {}, "c": {}}}}
        src = toolschema.analyze_source(self.tmp.name)
        r = toolschema.check(spec, src)
        kinds = [f["kind"] for f in r["findings"]]
        self.assertIn("required_param_missing", kinds)

    def test_unverifiable_is_reported_not_guessed(self):
        spec = {"description": "返回列表", "parameters": {"properties": {}}}
        src = toolschema.analyze_source(self.tmp.name)
        r = toolschema.check(spec, src)
        self.assertIn("unverifiable", r)

    def test_does_not_rewrite_spec(self):
        """防呆：只报告，不改描述。"""
        spec = {"description": "返回列表", "parameters": {"properties": {}}}
        before = json.dumps(spec, sort_keys=True)
        src = toolschema.analyze_source(self.tmp.name)
        toolschema.check(spec, src)
        self.assertEqual(json.dumps(spec, sort_keys=True), before)
