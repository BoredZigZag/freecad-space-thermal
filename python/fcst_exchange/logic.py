# SPDX-License-Identifier: MIT OR Apache-2.0
"""Reviewed pure-expression translation; source text is never evaluated."""
import ast
import math
from fcst_contracts import BUNDLE

LANGUAGE = "fcst-expr/1"
PROCEDURE_LANGUAGE = "fcst-pure-return/1"
LOCAL_PROCEDURE_LANGUAGE = "fcst-pure-return/2"
PROCEDURE_LANGUAGES = {PROCEDURE_LANGUAGE, LOCAL_PROCEDURE_LANGUAGE}
REGRESSION = "EXCHANGE-LOGIC-001"


def translate(text, language, symbols):
    from .core import reject
    if not isinstance(language,str) or language not in {LANGUAGE, *PROCEDURE_LANGUAGES}:
        reject("unreviewed_language")
    if not isinstance(text, str) or len(text.encode("utf-8")) > 4096:
        reject("expression_limit")
    try:
        tree = ast.parse(text, mode="exec" if language == LOCAL_PROCEDURE_LANGUAGE else "eval")
    except (ValueError, SyntaxError, RecursionError):
        reject("expression_syntax")
    if sum(1 for _ in ast.walk(tree)) > 256:
        reject("expression_limit")
    binary = {ast.Add:"add", ast.Sub:"subtract", ast.Mult:"multiply", ast.Div:"divide"}
    functions = {"abs":1, "sqrt":1, "exp":1, "log":1, "sin":1, "cos":1, "min":2, "max":2}
    locals_ = {}
    referenced = set()
    def number(node):
        sign = 1
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            sign = -1 if isinstance(node.op, ast.USub) else 1
            node = node.operand
        if not isinstance(node, ast.Constant) or type(node.value) not in (int, float):
            reject("expression_syntax")
        try:
            value = sign * float(node.value)
        except (OverflowError, ValueError):
            reject("expression_range")
        if not math.isfinite(value):
            reject("expression_range")
        return value
    def visit(node, depth=0):
        if depth > 12:
            reject("expression_limit")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return {"op":"literal", "quantity":{"value":number(node), "unit":"1"}}
        if isinstance(node, ast.Name) and node.id in locals_:
            referenced.add(node.id)
            return locals_[node.id]
        if isinstance(node, ast.Name) and node.id in symbols:
            return {"op":"symbol", "expression_id":symbols[node.id]}
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            return {"op":binary[type(node.op)], "args":[visit(node.left, depth+1), visit(node.right, depth+1)]}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return {"op":"negate", "args":[visit(node.operand, depth+1)]}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name == "quantity" and len(node.args) == 2:
                unit = node.args[1]
                if not isinstance(unit, ast.Constant) or type(unit.value) is not str or unit.value not in BUNDLE["units"]:
                    reject("expression_unit")
                return {"op":"literal", "quantity":{"value":number(node.args[0]), "unit":unit.value}}
            if name in functions and len(node.args) == functions[name]:
                return {"op":name, "args":[visit(arg, depth+1) for arg in node.args]}
        reject("untranslated_logic")
    if language != LOCAL_PROCEDURE_LANGUAGE:
        return visit(tree.body)

    if not tree.body or len(tree.body) > 17 or not isinstance(tree.body[-1], ast.Return):
        reject("untranslated_logic")
    for statement in tree.body[:-1]:
        if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)):
            reject("untranslated_logic")
        name = statement.targets[0].id
        if name in locals_ or name in symbols or name in functions or name == "quantity":
            reject("untranslated_logic")
        locals_[name] = visit(statement.value)
    result = visit(tree.body[-1].value)
    if set(locals_) != referenced:
        reject("untranslated_logic")
    # Bound the expanded pure expression before serialization and validation.
    pending = [(result, 0)]
    nodes = 0
    while pending:
        node, depth = pending.pop()
        nodes += 1
        if depth > 12 or nodes > 256:
            reject("expression_limit")
        pending.extend((child, depth+1) for child in node.get("args", ()))
    return result
