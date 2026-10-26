"""着色器数学的小语言：一份 Python 子集的赋值语句描述逐样本的浮点数学，编译成只含原语的有向无环图。

语言只有浮点数：数字、输入名、常量名、前面赋过值的名字、+ - * / **、单个 < 或 >（结果是 1.0 或 0.0）、a if c else b（两支都算）、
内建函数和 def 宏（若干赋值后跟一个 return，调用时原地展开，宏里只看得见常量、输入、内建与它的参数和自己的局部名字）。同一个名字只赋一次。
编译时折叠全是常量的子式，相同的子式只算一次，没有被输出用到的子式丢掉。numpy 后端与节点后端各自逐节点解释这张图，所以两边的数学是同一份。
不引用 bpy。
"""

import ast
from collections import namedtuple

import numpy as np

from . import primitives

Node = namedtuple("Node", ("op", "args", "value"))
Program = namedtuple("Program", ("nodes", "inputs", "outputs", "tables"))
Table = namedtuple("Table", ("positions", "values"))

CONSTANT = "const"
INPUT = "input"
TABLE = "table"
BINARY_OPERATORS = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.Pow: "pow"}
COMPARISONS = {ast.Lt: "lt", ast.Gt: "gt"}
DIRECT_FUNCTIONS = frozenset(("abs", "floor", "ceil", "fract", "sqrt", "exp", "ln", "sin", "cos", "tan", "tanh", "sign", "round", "trunc",
                              "min", "max", "atan2", "pow", "madd", "wn1", "wn2", "wn3"))
FOLDABLE = frozenset(primitives.PRIMITIVES)


class LanguageError(ValueError):
    pass


class _Builder:
    def __init__(self, input_names, constants, tables):
        self.nodes = []
        self.memo = {}
        self.inputs = {name: self._add(INPUT, (), name) for name in input_names}
        self.constants = {name: self.constant(value) for name, value in constants.items()}
        self.tables = tables
        self.macros = {}

    def _add(self, op, args, value=None):
        key = (op, args, value)
        if key not in self.memo:
            self.memo[key] = len(self.nodes)
            self.nodes.append(Node(op, args, value))
        return self.memo[key]

    def constant(self, value):
        return self._add(CONSTANT, (), float(np.float32(value)))

    def op(self, name, *args):
        if len(args) != primitives.arity(name):
            raise LanguageError("%s 要 %d 个参数，给了 %d 个" % (name, primitives.arity(name), len(args)))
        if name in FOLDABLE and all(self.nodes[arg].op == CONSTANT for arg in args):
            folded = primitives.PRIMITIVES[name](*(np.float32(self.nodes[arg].value) for arg in args))
            return self.constant(folded)
        return self._add(name, tuple(args))

    def table(self, name, argument):
        return self._add(TABLE, (argument,), name)

    def mix(self, first, second, fraction):
        return self.op("madd", self.op("sub", second, first), fraction, first)

    def saturate(self, value):
        return self.op("max", self.op("min", value, self.constant(1.0)), self.constant(0.0))

    def smoothstep(self, value):
        clamped = self.saturate(value)
        return self.op("mul", self.op("mul", clamped, clamped), self.op("madd", clamped, self.constant(-2.0), self.constant(3.0)))

    def call(self, name, arguments):
        if name in self.macros:
            return self._expand(name, arguments)
        if name in self.tables:
            self._arity(name, arguments, 1)
            return self.table(name, arguments[0])
        if name in DIRECT_FUNCTIONS:
            return self.op(name, *arguments)
        composites = {
            "mix": (3, lambda a, b, t: self.mix(a, b, t)),
            "select": (3, lambda condition, a, b: self.mix(b, a, condition)),
            "clamp": (3, lambda value, low, high: self.op("max", self.op("min", value, high), low)),
            "saturate": (1, self.saturate),
            "smoothstep": (1, self.smoothstep),
            "square": (1, lambda value: self.op("mul", value, value)),
            "hypot": (2, lambda a, b: self.op("sqrt", self.op("madd", a, a, self.op("mul", b, b)))),
        }
        if name not in composites:
            raise LanguageError("未知函数 %s" % name)
        count, build = composites[name]
        self._arity(name, arguments, count)
        return build(*arguments)

    @staticmethod
    def _arity(name, arguments, count):
        if len(arguments) != count:
            raise LanguageError("%s 要 %d 个参数，给了 %d 个" % (name, count, len(arguments)))

    def _expand(self, name, arguments):
        macro = self.macros[name]
        names = [argument.arg for argument in macro.args.args]
        self._arity(name, arguments, len(names))
        scope = dict(self.constants)
        scope.update(self.inputs)
        scope.update(zip(names, arguments))
        for statement in macro.body[:-1]:
            scope[statement.targets[0].id] = self.visit(statement.value, scope)
        return self.visit(macro.body[-1].value, scope)

    def visit(self, node, scope):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return self.constant(node.value)
        if isinstance(node, ast.Name):
            if node.id not in scope:
                raise LanguageError("第 %d 行：没有定义 %s" % (node.lineno, node.id))
            return scope[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = self.visit(node.operand, scope)
            return self.op("mul", value, self.constant(-1.0)) if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
            return self.op(BINARY_OPERATORS[type(node.op)], self.visit(node.left, scope), self.visit(node.right, scope))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARISONS:
            return self.op(COMPARISONS[type(node.ops[0])], self.visit(node.left, scope), self.visit(node.comparators[0], scope))
        if isinstance(node, ast.IfExp):
            return self.mix(self.visit(node.orelse, scope), self.visit(node.body, scope), self.visit(node.test, scope))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            return self.call(node.func.id, [self.visit(argument, scope) for argument in node.args])
        raise LanguageError("第 %d 行：不支持的写法 %s" % (getattr(node, "lineno", 0), type(node).__name__))


def _prune(nodes, inputs, outputs):
    reachable = set(outputs.values())
    for index in range(len(nodes) - 1, -1, -1):
        if index in reachable:
            reachable.update(nodes[index].args)
    remap = {}
    kept = []
    for index, node in enumerate(nodes):
        if index in reachable:
            remap[index] = len(kept)
            kept.append(Node(node.op, tuple(remap[arg] for arg in node.args), node.value))
    return kept, {name: remap[index] for name, index in inputs.items() if index in remap}, {name: remap[index] for name, index in outputs.items()}


def compile_source(source, input_names, output_names, constants, tables):
    """source 是语句文本；返回 Program(nodes, inputs, outputs, tables)，inputs 只含被用到的输入。"""
    builder = _Builder(input_names, constants, {name: Table(*table) for name, table in tables.items()})
    scope = dict(builder.constants)
    scope.update(builder.inputs)
    assigned = {}
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.FunctionDef):
            lead, last = statement.body[:-1], statement.body[-1]
            if not isinstance(last, ast.Return) or not all(isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name) for item in lead):
                raise LanguageError("第 %d 行：宏 %s 只能是若干赋值加最后一个 return" % (statement.lineno, statement.name))
            builder.macros[statement.name] = statement
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            name = statement.targets[0].id
            if name in scope:
                raise LanguageError("第 %d 行：%s 已经定义过" % (statement.lineno, name))
            scope[name] = assigned[name] = builder.visit(statement.value, scope)
        else:
            raise LanguageError("第 %d 行：只能写赋值或 def" % statement.lineno)
    missing = [name for name in output_names if name not in assigned]
    if missing:
        raise LanguageError("没有给输出赋值：%s" % missing)
    outputs = {name: assigned[name] for name in output_names}
    nodes, inputs, outputs = _prune(builder.nodes, builder.inputs, outputs)
    return Program(nodes, inputs, outputs, builder.tables)
