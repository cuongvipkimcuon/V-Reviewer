# utils/python_executor.py - V6 MODULE 4: PYTHON AUTONOMOUS CORE (The Calculator)
"""
Sandbox executor: run generated Pandas/NumPy code with restricted globals.
Workflow: AI writes script from extracted JSON -> System executes -> Returns exact number or result.
"""
import json
from typing import Any, Dict, Optional, Tuple

# Restricted builtins and modules for exec()
import math
import numpy as np
import pandas as pd


# Safe builtins (no file I/O, no eval/exec, no open, no __import__)
def _safe_builtins() -> Dict[str, Any]:
    safe = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "pow": pow,
        "print": print,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "True": True,
        "False": False,
        "None": None,
    }
    return safe


def _restricted_globals() -> Dict[str, Any]:
    """Globals allowed in exec(): pandas as pd, numpy as np, math, json, and safe builtins."""
    g = _safe_builtins()
    g["pd"] = pd
    g["pandas"] = pd
    g["np"] = np
    g["numpy"] = np
    g["math"] = math
    g["json"] = json
    return g


class PythonExecutor:
    """
    Sandbox executor using exec() with restricted globals.
    Use for AI-generated Pandas/NumPy scripts (e.g. from extracted JSON).
    """

    @staticmethod
    def execute(
        code: str,
        timeout_seconds: float = 10.0,
        result_variable: str = "result",
    ) -> Tuple[Optional[Any], Optional[str]]:
        """
        Execute code in sandbox. Expects code to assign final value to a variable (default `result`).
        Returns (value, None) on success, or (None, error_message) on failure.
        """
        import signal
        g = _restricted_globals()
        g["__builtins__"] = _safe_builtins()
        l = {}
        try:
            exec(code, g, l)
        except Exception as e:
            return None, str(e)
        out = l.get(result_variable)
        return out, None

    @staticmethod
    def execute_and_serialize(
        code: str,
        result_variable: str = "result",
        timeout_seconds: float = 10.0,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Execute code and serialize result to JSON-friendly form.
        Returns (json_string_or_simple_value, None) or (None, error_message).
        """
        val, err = PythonExecutor.execute(code, timeout_seconds=timeout_seconds, result_variable=result_variable)
        if err:
            return None, err
        if val is None:
            return "null", None
        try:
            if isinstance(val, (int, float, bool, str)):
                return json.dumps(val), None
            if isinstance(val, (list, dict)):
                return json.dumps(val, default=str), None
            if hasattr(val, "tolist"):
                return json.dumps(val.tolist()), None
            if hasattr(val, "to_dict"):
                return json.dumps(val.to_dict(), default=str), None
            return str(val), None
        except Exception as e:
            return None, "Serialize error: %s" % e
