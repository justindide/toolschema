"""toolschema —— 校验工具调用描述与实际行为是否一致。

设计原则：
1. **格式对不代表语义对**。描述说「返回列表」而实现返回字典，
   schema 校验抓不到，但每次调用都会悄悄出错。
2. **只查能机械判定的不一致**，不猜语义。查不出来的明说查不出来。
3. **不改描述**。只报告，让人来改。

仅依赖 Python 标准库。

用法:
    python toolschema.py --help
    python toolschema.py --spec tool.json --source tool.py
    python toolschema.py --spec tool.json --source tool.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys

# ---------------------------------------------------------------------------
# 描述里的声明
# ---------------------------------------------------------------------------

# 从描述文本里抽「声明」：返回类型、单位、必填性
RETURN_TYPE_RE = re.compile(
    r"(返回|return(?:s)?)\s*(?:一个|一个\s*)?"
    r"(列表|数组|list|array|字典|dict|对象|object|字符串|string|"
    r"布尔|bool|布尔值|数字|number|整数|int|空|空值|null|none)", re.I)

UNIT_RE = re.compile(
    r"(单位(?:是|为)\s*|以\s*|in\s+)?"
    r"(秒|毫秒|微秒|分钟|小时|天|bytes?|字节|KB|MB|GB|米|厘米|千克|美元|元|"
    r"tokens?|字符|字)", re.I)

BOOLEAN_RE = re.compile(r"(布尔|bool|true\s*/\s*false|是或否)", re.I)

NULLABLE_RE = re.compile(r"(可能为\s*(空|null|none)|可为空|或为空|没有时返回空)", re.I)

# 返回类型 → 期望的 python 类型名
RETURN_TYPE_MAP = {
    "列表": "list", "数组": "list", "list": "list", "array": "list",
    "字典": "dict", "dict": "dict", "对象": "dict", "object": "dict",
    "字符串": "str", "string": "str",
    "布尔": "bool", "bool": "bool", "布尔值": "bool",
    "数字": "float", "number": "float", "整数": "int", "int": "int",
    "空": "None", "null": "None", "none": "None", "空值": "None",
}


def extract_claims(description: str) -> list[dict]:
    """从描述里抽出可核对的声明。"""
    claims: list[dict] = []
    desc = description or ""

    m = RETURN_TYPE_RE.search(desc)
    if m:
        raw = m.group(2).lower()
        claims.append({
            "kind": "return_type",
            "claimed": raw,
            "expected_python_type": RETURN_TYPE_MAP.get(
                m.group(2), RETURN_TYPE_MAP.get(raw, "")),
            "evidence": m.group(0),
        })

    m = UNIT_RE.search(desc)
    if m:
        claims.append({
            "kind": "unit",
            "claimed": m.group(2).lower(),
            "evidence": m.group(0),
        })

    if BOOLEAN_RE.search(desc):
        claims.append({"kind": "boolean", "claimed": "bool", "evidence": "布尔"})

    if NULLABLE_RE.search(desc):
        claims.append({"kind": "nullable", "claimed": "True", "evidence": "可能为空"})

    return claims


# ---------------------------------------------------------------------------
# 从源码里抽实际行为
# ---------------------------------------------------------------------------

class ReturnCollector(ast.NodeVisitor):
    """扫函数体，收集 return 出去的表达式类型。"""

    def __init__(self) -> None:
        self.return_types: list[str] = []
        self.return_exprs: list[str] = []
        self.function_names: list[str] = []
        self.docstring: str = ""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_names.append(node.name)
        if not self.docstring:
            self.docstring = ast.get_docstring(node) or ""
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is None:
            self.return_types.append("None")
            self.return_exprs.append("")
            return
        try:
            src = ast.unparse(node.value)
        except Exception:  # noqa: BLE001
            src = ""
        self.return_exprs.append(src)
        self.return_types.append(self._infer(node.value))

    @staticmethod
    def _infer(node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            if node.value is None:
                return "None"
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, str):
                return "str"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, float):
                return "float"
            return "unknown"
        if isinstance(node, (ast.List, ast.ListComp)):
            return "list"
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return "dict"
        if isinstance(node, (ast.Set, ast.SetComp)):
            return "set"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, ast.JoinedStr):
            return "str"
        if isinstance(node, ast.Name):
            # x = [] 之类，看变量名
            if node.id in ("True", "False"):
                return "bool"
            if node.id in ("None",):
                return "None"
            return "unknown"
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                return {"list": "list", "dict": "dict", "str": "str",
                        "int": "int", "float": "float", "bool": "bool",
                        "set": "set", "tuple": "tuple"}.get(fn.id, "unknown")
            if isinstance(fn, ast.Attribute):
                return fn.attr
        if isinstance(node, ast.IfExp):
            # 三元表达式：两支都看
            a = ReturnCollector._infer(node.body)
            b = ReturnCollector._infer(node.orelse)
            return a if a == b else f"{a}|{b}"
        return "unknown"


def analyze_source(path: str) -> dict:
    """从源码里抽实际返回行为。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        raise ValueError(f"读不了源码 {path}：{e}") from e

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"源码语法错误 {path}：{e}") from e

    collector = ReturnCollector()
    collector.visit(tree)

    # 数字字面量后缀 → 单位线索（比如 _ms / _s 后缀的变量）
    unit_vars = set()
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)_(ms|s|sec|seconds|"
                         r"bytes|b|kb|mb|gb|chars?|tokens?)\b", source):
        unit_vars.add(m.group(0).lower())

    return {
        "return_types": collector.return_types,
        "return_exprs": collector.return_exprs,
        "functions": collector.function_names,
        "docstring": collector.docstring,
        "unit_vars": sorted(unit_vars),
        "source": source,
    }


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

# 描述里说的单位 → 源码里出现的后缀
UNIT_SUFFIX = {
    "秒": "s", "毫秒": "ms", "微秒": "us",
    "分钟": "min", "小时": "h", "天": "d",
    "bytes": "b", "字节": "b", "kb": "kb", "mb": "mb", "gb": "gb",
    "字符": "chars", "字": "chars", "tokens": "tokens", "token": "tokens",
}


def check(spec: dict, src: dict) -> dict:
    """比对描述与实现。"""
    description = spec.get("description", "")
    claims = extract_claims(description)
    findings: list[dict] = []
    unverifiable: list[dict] = []

    actual_types = [t for t in src["return_types"]]
    type_set = set(actual_types)
    # 拆开 a|b 这种联合类型
    for t in list(type_set):
        if "|" in t:
            type_set.discard(t)
            type_set.update(t.split("|"))

    for claim in claims:
        if claim["kind"] == "return_type":
            expected = claim.get("expected_python_type")
            if not expected:
                unverifiable.append({"claim": claim["evidence"],
                                     "reason": "描述里的返回类型无法映射到具体类型"})
                continue
            if not type_set:
                unverifiable.append({
                    "claim": claim["evidence"],
                    "reason": "实现里的返回表达式无法静态判定",
                })
            elif expected not in type_set:
                findings.append({
                    "kind": "return_type_mismatch",
                    "severity": 3,
                    "claimed": claim["claimed"],
                    "expected_python_type": expected,
                    "actual_types": sorted(type_set),
                    "detail": f"描述说返回「{claim['claimed']}」，"
                              f"实现里返回的是 {'、'.join(sorted(type_set)) or '（没有 return）'}",
                })

        elif claim["kind"] == "unit":
            suffix = UNIT_SUFFIX.get(claim["claimed"])
            if not suffix:
                unverifiable.append({"claim": claim["evidence"],
                                     "reason": "单位无法对应到命名后缀"})
                continue
            if src["unit_vars"] and not any(
                    v.endswith("_" + suffix) for v in src["unit_vars"]):
                findings.append({
                    "kind": "unit_mismatch",
                    "severity": 2,
                    "claimed": claim["claimed"],
                    "detail": f"描述说单位是「{claim['claimed']}」，"
                              f"但源码里的量都没有 _{suffix} 后缀",
                })
            elif not src["unit_vars"]:
                unverifiable.append({
                    "claim": claim["evidence"],
                    "reason": "源码里没有可判断单位的命名线索",
                })

    # 参数模式与实现签名
    schema = spec.get("parameters") or spec.get("input_schema") or {}
    required = schema.get("required") or []
    params = schema.get("properties") or {}
    func_name = spec.get("function") or ""
    signature_params: list[str] = []
    if src["functions"]:
        # 尽量找与 spec 同名的函数
        target = func_name or src["functions"][-1]
        try:
            tree = ast.parse(src["source"])
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == target:
                    signature_params = [a.arg for a in node.args.args
                                        if a.arg != "self"]
                    break
        except SyntaxError:
            pass
        if not signature_params:
            signature_params = [a for a in src["functions"]]

    if signature_params and required:
        missing = [p for p in required if p not in signature_params]
        if missing:
            findings.append({
                "kind": "required_param_missing",
                "severity": 3,
                "detail": f"声明为必填的参数在实现里没有：{'、'.join(missing)}",
            })

    # 声明了但实现里没有的参数
    if params and signature_params:
        unknown = [p for p in params if p not in signature_params]
        if unknown:
            findings.append({
                "kind": "param_not_in_signature",
                "severity": 2,
                "detail": f"参数模式声明了但实现签名里没有：{'、'.join(unknown)}",
            })

    findings.sort(key=lambda f: -f["severity"])
    return {
        "findings": findings,
        "unverifiable": unverifiable,
        "claims": claims,
        "actual_return_types": sorted(type_set),
        "functions": src["functions"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(result: dict) -> str:
    out: list[str] = []
    out.append("工具描述一致性校验")
    out.append("=" * 60)
    out.append(f"实现中的返回类型：{'、'.join(result['actual_return_types']) or '（无）'}")
    out.append(f"识别到的函数：{'、'.join(result['functions']) or '（无）'}")
    out.append("")

    if result["findings"]:
        out.append("不一致：")
        for f in result["findings"]:
            out.append(f"  [{f['kind']}]  {f['detail']}")
        out.append("")
    else:
        out.append("未发现可判定的不一致。")
        out.append("")

    if result["unverifiable"]:
        out.append("以下声明无法静态判定（需要人工确认）：")
        for u in result["unverifiable"]:
            out.append(f"  · 「{u['claim']}」—— {u['reason']}")
        out.append("")

    out.append("注：本工具只做机械比对。语义层面的「描述是否说清了」仍需人读。")
    return "\n".join(out).rstrip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="toolschema",
        description="校验工具调用描述与实际行为是否一致（仅依赖标准库）",
        epilog=(
            "spec 文件：\n"
            "  {\"name\":\"calc\",\"description\":\"返回差值，单位是秒\",\n"
            "   \"parameters\":{\"required\":[\"a\"],\"properties\":{\"a\":{}}}}\n"
            "  python toolschema.py --spec tool.json --source tool.py\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--spec", required=True, help="工具描述 JSON")
    ap.add_argument("--source", required=True, help="实现源码路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    try:
        with open(args.spec, "r", encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"读不了 spec：{e}", file=sys.stderr)
        return 2

    try:
        src = analyze_source(args.source)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    result = check(spec, src)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(render(result))
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
