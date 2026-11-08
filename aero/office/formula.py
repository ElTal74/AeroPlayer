"""Evaluador de fórmulas de hoja de cálculo (subconjunto honesto de Excel).

Admite: números, textos, VERDADERO/FALSO, referencias (A1, $A$1, Hoja!A1, 'Mi hoja'!A1), rangos (A1:B5),
operadores + − * / ^ & = <> < > <= >=, porcentajes (50%) y estas funciones (nombres en inglés o en
español): SUM/SUMA, AVERAGE/PROMEDIO, MIN, MAX, COUNT/CONTAR, COUNTA/CONTARA, IF/SI, ROUND/REDONDEAR,
ABS, AND/Y, OR/O, NOT/NO, CONCAT/CONCATENAR, LEN/LARGO, UPPER/MAYUSC, LOWER/MINUSC, SUMIF/SUMAR.SI,
COUNTIF/CONTAR.SI, IFERROR/SI.ERROR, PRODUCT/PRODUCTO, SQRT/RAIZ, INT/ENTERO, MOD/RESIDUO.

Las fórmulas se guardan tal cual en el archivo (el evaluador solo calcula lo que se muestra). Una función
no admitida devuelve el valor guardado por la aplicación que creó el archivo, si existe, o «#¿NOMBRE?».
"""

from __future__ import annotations

import math
import re

from openpyxl.utils import column_index_from_string, get_column_letter


class FormulaError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


ERRORS = ("#¡DIV/0!", "#¡VALOR!", "#¿NOMBRE?", "#¡REF!", "#N/A", "#¡NUM!", "#CIRC!")

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<ref>(?:(?:'[^']+'|[A-Za-z_][\w.]*)!)?\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)
  | (?P<num>\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?%?)
  | (?P<func>[A-Za-z_][\w.]*(?=\())
  | (?P<bool>TRUE|FALSE|VERDADERO|FALSO)\b
  | (?P<op><>|<=|>=|[-+*/^&=<>(),;:])
""", re.VERBOSE | re.IGNORECASE)

ALIASES = {"SUMA": "SUM", "PROMEDIO": "AVERAGE", "CONTAR": "COUNT", "CONTARA": "COUNTA", "SI": "IF",
           "REDONDEAR": "ROUND", "Y": "AND", "O": "OR", "NO": "NOT", "CONCATENAR": "CONCATENATE",
           "LARGO": "LEN", "MAYUSC": "UPPER", "MINUSC": "LOWER", "SUMAR.SI": "SUMIF", "CONTAR.SI": "COUNTIF",
           "SI.ERROR": "IFERROR", "PRODUCTO": "PRODUCT", "RAIZ": "SQRT", "ENTERO": "INT", "RESIDUO": "MOD",
           "CONCAT": "CONCATENATE"}


def tokenize(src: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise FormulaError("#¿NOMBRE?")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group()))
    return out


def split_ref(ref: str) -> tuple[str | None, str]:
    if "!" in ref:
        sheet, cell = ref.rsplit("!", 1)
        return sheet.strip("'"), cell
    return None, ref


def cell_rc(a1: str) -> tuple[int, int]:
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", a1)
    if not m:
        raise FormulaError("#¡REF!")
    return int(m.group(2)), column_index_from_string(m.group(1).upper())


class Evaluator:
    """Evalúa fórmulas sobre un libro de openpyxl. `cached` da valores guardados por Excel (si los hay)."""

    def __init__(self, wb, cached=None):
        self.wb = wb
        self.cached = cached
        self.memo: dict[tuple[str, int, int], object] = {}
        self.stack: set[tuple[str, int, int]] = set()

    def invalidate(self):
        self.memo.clear()

    # ------------------------------------------------------------------ valores
    def value(self, sheet: str, row: int, col: int):
        key = (sheet, row, col)
        if key in self.memo:
            return self.memo[key]
        ws = self.wb[sheet]
        v = ws.cell(row, col).value
        if isinstance(v, str) and v.startswith("="):
            if key in self.stack:
                return "#CIRC!"
            self.stack.add(key)
            try:
                v = self.evaluate(v, sheet)
            except FormulaError as e:
                v = e.code
                if e.code == "#¿NOMBRE?" and self.cached is not None:
                    try:
                        c = self.cached[sheet].cell(row, col).value
                        if c is not None:
                            v = c
                    except KeyError:
                        pass
            finally:
                self.stack.discard(key)
        self.memo[key] = v
        return v

    def evaluate(self, formula: str, sheet: str):
        toks = tokenize(formula.lstrip("="))
        # Reentrante: una celda puede necesitar el valor de otra con fórmula a mitad de este análisis
        saved = getattr(self, "_t", None), getattr(self, "_i", 0), getattr(self, "_sheet", sheet)
        self._t, self._i, self._sheet = toks, 0, sheet
        try:
            v = self._expr()
            if self._i != len(self._t):
                raise FormulaError("#¡VALOR!")
        finally:
            self._t, self._i, self._sheet = saved
        if isinstance(v, list):
            v = v[0] if v else 0
        return v

    # ------------------------------------------------------------------ análisis descendente
    def _peek(self):
        return self._t[self._i] if self._i < len(self._t) else (None, None)

    def _eat(self, text=None):
        tok = self._peek()
        if tok[0] is None or (text is not None and tok[1] != text):
            raise FormulaError("#¡VALOR!")
        self._i += 1
        return tok

    def _expr(self):
        left = self._concat()
        while self._peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self._eat()[1]
            right = self._concat()
            a, b = _scalar(left), _scalar(right)
            if isinstance(a, str) or isinstance(b, str):
                a, b = str(a).lower(), str(b).lower()
            left = {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        return left

    def _concat(self):
        left = self._add()
        while self._peek()[1] == "&":
            self._eat()
            left = _text(_scalar(left)) + _text(_scalar(self._add()))
        return left

    def _add(self):
        left = self._mul()
        while self._peek()[1] in ("+", "-"):
            op = self._eat()[1]
            right = self._mul()
            left = _num(left) + _num(right) if op == "+" else _num(left) - _num(right)
        return left

    def _mul(self):
        left = self._pow()
        while self._peek()[1] in ("*", "/"):
            op = self._eat()[1]
            right = self._pow()
            if op == "*":
                left = _num(left) * _num(right)
            else:
                d = _num(right)
                if d == 0:
                    raise FormulaError("#¡DIV/0!")
                left = _num(left) / d
        return left

    def _pow(self):
        left = self._unary()
        while self._peek()[1] == "^":
            self._eat()
            left = _num(left) ** _num(self._unary())
        return left

    def _unary(self):
        if self._peek()[1] == "-":
            self._eat()
            return -_num(self._unary())
        if self._peek()[1] == "+":
            self._eat()
            return _num(self._unary())
        return self._atom()

    def _atom(self):
        kind, text = self._eat()
        if kind == "num":
            pct = text.endswith("%")
            v = float(text.rstrip("%").replace(",", "."))
            return v / 100 if pct else v
        if kind == "str":
            return text[1:-1].replace('""', '"')
        if kind == "bool":
            return text.upper() in ("TRUE", "VERDADERO")
        if kind == "ref":
            return self._ref(text)
        if kind == "func":
            return self._call(text.upper())
        if text == "(":
            v = self._expr()
            self._eat(")")
            return v
        raise FormulaError("#¡VALOR!")

    def _ref(self, text: str):
        sheet, ref = split_ref(text)
        sheet = sheet or self._sheet
        if sheet not in self.wb.sheetnames:
            raise FormulaError("#¡REF!")
        if ":" in ref:
            a, b = ref.split(":")
            r0, c0 = cell_rc(a)
            r1, c1 = cell_rc(b)
            ws = self.wb[sheet]
            r1 = min(max(r0, r1), max(r0, ws.max_row))
            return [self.value(sheet, r, c) for r in range(min(r0, r1), r1 + 1)
                    for c in range(min(c0, c1), max(c0, c1) + 1)]
        r, c = cell_rc(ref)
        return self.value(sheet, r, c)

    def _args(self) -> list:
        self._eat("(")
        args = []
        if self._peek()[1] == ")":
            self._eat(")")
            return args
        while True:
            args.append(self._expr())
            if self._peek()[1] in (",", ";"):
                self._eat()
                continue
            self._eat(")")
            return args

    def _arg_slices(self) -> list[list]:
        """Tokens de cada argumento (sin evaluarlos), avanzando hasta el paréntesis de cierre."""
        self._eat("(")
        parts, cur, depth = [], [], 0
        while True:
            tok = self._eat()
            if tok[1] == "(":
                depth += 1
            elif tok[1] == ")":
                if depth == 0:
                    parts.append(cur)
                    return parts
                depth -= 1
            elif tok[1] in (",", ";") and depth == 0:
                parts.append(cur)
                cur = []
                continue
            cur.append(tok)

    def _sub(self, toks: list):
        saved = self._t, self._i
        self._t, self._i = toks, 0
        try:
            v = self._expr()
            if self._i != len(toks):
                raise FormulaError("#¡VALOR!")
            return v
        finally:
            self._t, self._i = saved

    def _call(self, name: str):
        name = ALIASES.get(name, name)
        if name == "IF":
            args = self._args()
            cond = _truth(args[0]) if args else False
            return (args[1] if len(args) > 1 else True) if cond else (args[2] if len(args) > 2 else False)
        if name == "IFERROR":
            parts = self._arg_slices()
            try:
                v = _scalar(self._sub(parts[0]))
                if isinstance(v, str) and v in ERRORS:
                    raise FormulaError(v)
                return v
            except FormulaError:
                return self._sub(parts[1]) if len(parts) > 1 else ""
        args = self._args()
        flat = [x for a in args for x in (a if isinstance(a, list) else [a])]
        nums = [x for x in flat if isinstance(x, (int, float)) and not isinstance(x, bool)]
        for x in flat:
            if isinstance(x, str) and x in ERRORS:
                raise FormulaError(x)
        if name == "SUM":
            return sum(nums)
        if name == "AVERAGE":
            if not nums:
                raise FormulaError("#¡DIV/0!")
            return sum(nums) / len(nums)
        if name == "MIN":
            return min(nums) if nums else 0
        if name == "MAX":
            return max(nums) if nums else 0
        if name == "COUNT":
            return len(nums)
        if name == "COUNTA":
            return sum(1 for x in flat if x not in (None, ""))
        if name == "PRODUCT":
            return math.prod(nums) if nums else 0
        if name == "ROUND":
            d = int(_num(args[1])) if len(args) > 1 else 0
            v = _num(args[0])
            return math.floor(v * 10 ** d + 0.5) / 10 ** d if v >= 0 else -math.floor(-v * 10 ** d + 0.5) / 10 ** d
        if name == "ABS":
            return abs(_num(args[0]))
        if name == "SQRT":
            v = _num(args[0])
            if v < 0:
                raise FormulaError("#¡NUM!")
            return math.sqrt(v)
        if name == "INT":
            return math.floor(_num(args[0]))
        if name == "MOD":
            d = _num(args[1])
            if d == 0:
                raise FormulaError("#¡DIV/0!")
            return _num(args[0]) % d
        if name == "AND":
            return all(_truth(x) for x in flat)
        if name == "OR":
            return any(_truth(x) for x in flat)
        if name == "NOT":
            return not _truth(args[0])
        if name == "CONCATENATE":
            return "".join(_text(x) for x in flat)
        if name == "LEN":
            return len(_text(_scalar(args[0])))
        if name == "UPPER":
            return _text(_scalar(args[0])).upper()
        if name == "LOWER":
            return _text(_scalar(args[0])).lower()
        if name in ("SUMIF", "COUNTIF"):
            rng = args[0] if isinstance(args[0], list) else [args[0]]
            test = _criterion(_scalar(args[1]))
            if name == "COUNTIF":
                return sum(1 for x in rng if test(x))
            vals = args[2] if len(args) > 2 and isinstance(args[2], list) else rng
            return sum(_num(v) for x, v in zip(rng, vals) if test(x) and isinstance(v, (int, float)))
        raise FormulaError("#¿NOMBRE?")


def _scalar(v):
    if isinstance(v, list):
        return v[0] if v else 0
    return v


def _num(v) -> float:
    v = _scalar(v)
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        if v in ERRORS:
            raise FormulaError(v)
        try:
            return float(v.replace(",", "."))
        except ValueError:
            raise FormulaError("#¡VALOR!") from None
    raise FormulaError("#¡VALOR!")


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "VERDADERO" if v else "FALSO"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _truth(v) -> bool:
    v = _scalar(v)
    if isinstance(v, str):
        if v.upper() in ("TRUE", "VERDADERO"):
            return True
        if v.upper() in ("FALSE", "FALSO", ""):
            return False
        raise FormulaError("#¡VALOR!")
    return bool(v)


def _criterion(c):
    if isinstance(c, str):
        m = re.match(r"^(<>|<=|>=|=|<|>)?(.*)$", c)
        op, rest = m.group(1) or "=", m.group(2)
        try:
            target = float(rest.replace(",", "."))
        except ValueError:
            target = rest.lower()
    else:
        op, target = "=", c

    def test(x):
        if x is None:
            return False
        a = x.lower() if isinstance(x, str) and isinstance(target, str) else x
        if isinstance(target, float) and not isinstance(a, (int, float)):
            return op == "<>"
        try:
            return {"=": a == target, "<>": a != target, "<": a < target, ">": a > target, "<=": a <= target,
                    ">=": a >= target}[op]
        except TypeError:
            return False
    return test


def a1(row: int, col: int) -> str:
    return f"{get_column_letter(col)}{row}"
