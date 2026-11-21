from typing import Dict, Any, Callable
import importlib

GATES: Dict[str, Dict[str, Any]] = {
    "point": {
        "id": "point",
        "name": "Point",
        "display_name": "Point",
        "command": "pu",
        "multi_command": "mapu",
        "module": "services.puan"
    }
}

DEFAULT_GATE_FUNCTIONS = {
    "services.puan": "query_card_points"
}

def get_gate_by_command(cmd: str):
    cmd = cmd.lower().lstrip("/")
    for gate in GATES.values():
        if gate.get("command") == cmd:
            return gate
    return None

def get_gate_handler(gate_info: Dict[str, Any]) -> Callable:
    module_name = gate_info["module"]
    mod = importlib.import_module(module_name)
    func_name = gate_info.get("function") or DEFAULT_GATE_FUNCTIONS.get(module_name)
    if not func_name:
        for attr in ["query_charge", "query_iyzico_charge", "query_card_points", "query"]:
            if hasattr(mod, attr):
                func_name = attr
                break
    return getattr(mod, func_name)
