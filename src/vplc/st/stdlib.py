"""IEC 61131-3 standard function blocks and functions."""

from __future__ import annotations

import math

from ..types import TYPES, IecType, coerce
from .errors import PLCRuntimeError

T = TYPES


class FunctionBlock:
    """Base class. Inputs/outputs are kept in ``values`` (upper-case keys)."""

    TYPE_NAME = ""
    INPUTS: dict[str, IecType] = {}
    OUTPUTS: dict[str, IecType] = {}

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        for name, t in {**self.INPUTS, **self.OUTPUTS}.items():
            self.values[name] = t.default

    def set_input(self, name: str, value) -> None:
        self.values[name] = coerce(self.INPUTS[name], value)

    def execute(self, now_ms: int) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def snapshot(self) -> dict:
        return dict(self.values)


class TON(FunctionBlock):
    """On-delay timer."""

    TYPE_NAME = "TON"
    INPUTS = {"IN": T["BOOL"], "PT": T["TIME"]}
    OUTPUTS = {"Q": T["BOOL"], "ET": T["TIME"]}

    def __init__(self) -> None:
        super().__init__()
        self._start: int | None = None

    def execute(self, now_ms: int) -> None:
        v = self.values
        if v["IN"]:
            if self._start is None:
                self._start = now_ms
            et = min(now_ms - self._start, v["PT"])
            v["ET"] = et
            v["Q"] = et >= v["PT"]
        else:
            self._start = None
            v["ET"] = 0
            v["Q"] = False


class TOF(FunctionBlock):
    """Off-delay timer."""

    TYPE_NAME = "TOF"
    INPUTS = {"IN": T["BOOL"], "PT": T["TIME"]}
    OUTPUTS = {"Q": T["BOOL"], "ET": T["TIME"]}

    def __init__(self) -> None:
        super().__init__()
        self._start: int | None = None
        self._prev_in = False

    def execute(self, now_ms: int) -> None:
        v = self.values
        if v["IN"]:
            v["Q"] = True
            v["ET"] = 0
            self._start = None
        else:
            if self._prev_in:
                self._start = now_ms
            if self._start is not None:
                et = min(now_ms - self._start, v["PT"])
                v["ET"] = et
                if et >= v["PT"]:
                    v["Q"] = False
                    self._start = None
        self._prev_in = v["IN"]


class TP(FunctionBlock):
    """Pulse timer."""

    TYPE_NAME = "TP"
    INPUTS = {"IN": T["BOOL"], "PT": T["TIME"]}
    OUTPUTS = {"Q": T["BOOL"], "ET": T["TIME"]}

    def __init__(self) -> None:
        super().__init__()
        self._start: int | None = None
        self._prev_in = False

    def execute(self, now_ms: int) -> None:
        v = self.values
        if self._start is None and v["IN"] and not self._prev_in:
            self._start = now_ms
        if self._start is not None:
            et = min(now_ms - self._start, v["PT"])
            v["ET"] = et
            v["Q"] = et < v["PT"]
            if et >= v["PT"] and not v["IN"]:
                self._start = None
                v["ET"] = 0
        elif not v["IN"]:
            v["ET"] = 0
        self._prev_in = v["IN"]


class R_TRIG(FunctionBlock):
    TYPE_NAME = "R_TRIG"
    INPUTS = {"CLK": T["BOOL"]}
    OUTPUTS = {"Q": T["BOOL"]}

    def __init__(self) -> None:
        super().__init__()
        self._m = False

    def execute(self, now_ms: int) -> None:
        clk = self.values["CLK"]
        self.values["Q"] = clk and not self._m
        self._m = clk


class F_TRIG(FunctionBlock):
    TYPE_NAME = "F_TRIG"
    INPUTS = {"CLK": T["BOOL"]}
    OUTPUTS = {"Q": T["BOOL"]}

    def __init__(self) -> None:
        super().__init__()
        self._m = False

    def execute(self, now_ms: int) -> None:
        clk = self.values["CLK"]
        self.values["Q"] = (not clk) and self._m
        self._m = clk


class CTU(FunctionBlock):
    TYPE_NAME = "CTU"
    INPUTS = {"CU": T["BOOL"], "R": T["BOOL"], "PV": T["INT"]}
    OUTPUTS = {"Q": T["BOOL"], "CV": T["INT"]}

    def __init__(self) -> None:
        super().__init__()
        self._prev = False

    def execute(self, now_ms: int) -> None:
        v = self.values
        if v["R"]:
            v["CV"] = 0
        elif v["CU"] and not self._prev and v["CV"] < 32767:
            v["CV"] += 1
        self._prev = v["CU"]
        v["Q"] = v["CV"] >= v["PV"]


class CTD(FunctionBlock):
    TYPE_NAME = "CTD"
    INPUTS = {"CD": T["BOOL"], "LD": T["BOOL"], "PV": T["INT"]}
    OUTPUTS = {"Q": T["BOOL"], "CV": T["INT"]}

    def __init__(self) -> None:
        super().__init__()
        self._prev = False

    def execute(self, now_ms: int) -> None:
        v = self.values
        if v["LD"]:
            v["CV"] = v["PV"]
        elif v["CD"] and not self._prev and v["CV"] > -32768:
            v["CV"] -= 1
        self._prev = v["CD"]
        v["Q"] = v["CV"] <= 0


class CTUD(FunctionBlock):
    TYPE_NAME = "CTUD"
    INPUTS = {"CU": T["BOOL"], "CD": T["BOOL"], "R": T["BOOL"], "LD": T["BOOL"], "PV": T["INT"]}
    OUTPUTS = {"QU": T["BOOL"], "QD": T["BOOL"], "CV": T["INT"]}

    def __init__(self) -> None:
        super().__init__()
        self._prev_u = False
        self._prev_d = False

    def execute(self, now_ms: int) -> None:
        v = self.values
        if v["R"]:
            v["CV"] = 0
        elif v["LD"]:
            v["CV"] = v["PV"]
        else:
            up = v["CU"] and not self._prev_u
            down = v["CD"] and not self._prev_d
            if up and not down and v["CV"] < 32767:
                v["CV"] += 1
            elif down and not up and v["CV"] > -32768:
                v["CV"] -= 1
        self._prev_u, self._prev_d = v["CU"], v["CD"]
        v["QU"] = v["CV"] >= v["PV"]
        v["QD"] = v["CV"] <= 0


class SR(FunctionBlock):
    """Set-dominant bistable."""

    TYPE_NAME = "SR"
    INPUTS = {"S1": T["BOOL"], "R": T["BOOL"]}
    OUTPUTS = {"Q1": T["BOOL"]}

    def execute(self, now_ms: int) -> None:
        v = self.values
        v["Q1"] = v["S1"] or (not v["R"] and v["Q1"])


class RS(FunctionBlock):
    """Reset-dominant bistable."""

    TYPE_NAME = "RS"
    INPUTS = {"S": T["BOOL"], "R1": T["BOOL"]}
    OUTPUTS = {"Q1": T["BOOL"]}

    def execute(self, now_ms: int) -> None:
        v = self.values
        v["Q1"] = not v["R1"] and (v["S"] or v["Q1"])


FUNCTION_BLOCKS: dict[str, type[FunctionBlock]] = {
    cls.TYPE_NAME: cls for cls in (TON, TOF, TP, R_TRIG, F_TRIG, CTU, CTD, CTUD, SR, RS)
}


# ------------------------------------------------------------------ functions
def _real(fn):
    def wrapper(x):
        try:
            return fn(float(x))
        except ValueError:
            return math.nan

    return wrapper


def _limit(mn, x, mx):
    return min(max(x, mn), mx)


def _sel(g, in0, in1):
    return in1 if g else in0


def _mux(k, *inputs):
    if not 0 <= int(k) < len(inputs):
        raise PLCRuntimeError(f"MUX: Index {k} außerhalb des Bereichs")
    return inputs[int(k)]


def _shl(x, n):
    return int(x) << int(n)


def _shr(x, n):
    return int(x) >> int(n)


FUNCTIONS: dict[str, tuple[object, int, int | None]] = {
    # name: (callable, min args, max args or None for variadic)
    "ABS": (abs, 1, 1),
    "SQRT": (_real(math.sqrt), 1, 1),
    "LN": (_real(math.log), 1, 1),
    "LOG": (_real(math.log10), 1, 1),
    "EXP": (_real(math.exp), 1, 1),
    "SIN": (_real(math.sin), 1, 1),
    "COS": (_real(math.cos), 1, 1),
    "TAN": (_real(math.tan), 1, 1),
    "ASIN": (_real(math.asin), 1, 1),
    "ACOS": (_real(math.acos), 1, 1),
    "ATAN": (_real(math.atan), 1, 1),
    "TRUNC": (lambda x: int(x), 1, 1),
    "MIN": (min, 2, None),
    "MAX": (max, 2, None),
    "LIMIT": (_limit, 3, 3),
    "SEL": (_sel, 3, 3),
    "MUX": (_mux, 2, None),
    "SHL": (_shl, 2, 2),
    "SHR": (_shr, 2, 2),
}


def _conversion(target: IecType):
    def convert(x):
        if target.kind in ("int", "time") and isinstance(x, float):
            if math.isnan(x) or math.isinf(x):
                raise PLCRuntimeError(f"Ungültiger Wert bei Umwandlung nach {target.name}")
            x = round(x)  # IEC: REAL_TO_INT rounds
        return coerce(target, x)

    return convert


for _src in TYPES:
    for _dst, _dst_t in TYPES.items():
        if _src != _dst:
            FUNCTIONS[f"{_src}_TO_{_dst}"] = (_conversion(_dst_t), 1, 1)
# Generic TO_<TYPE> conversions (IEC 61131-3 3rd edition)
for _dst, _dst_t in TYPES.items():
    FUNCTIONS[f"TO_{_dst}"] = (_conversion(_dst_t), 1, 1)
