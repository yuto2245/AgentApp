import json
from typing import Any, Dict

from chainlit.data.chainlit_data_layer import ChainlitDataLayer
from chainlit.step import StepDict
from typing import cast


def _to_json_str(value: Any, wrap_text: bool = False) -> str | None:
    """Ensure value is a JSON string suitable for JSONB columns."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except Exception:
            if wrap_text:
                return json.dumps({"text": value}, ensure_ascii=False)
            return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (dict, list, int, float, bool)):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "dict"):
        return json.dumps(value.dict(), ensure_ascii=False)
    if hasattr(value, "__dict__"):
        return json.dumps(value.__dict__, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def _to_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            return {"value": value}
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": value}


class AppDataLayer(ChainlitDataLayer):
    """Normalize step payloads before delegating to default Chainlit data layer."""

    def _prepare_step(self, step_dict: StepDict) -> StepDict:
        # TypedDict does not support isinstance checks, so make a shallow copy explicitly.
        prepared: StepDict = cast(StepDict, dict(step_dict))
        prepared["input"] = _to_json_str(step_dict.get("input"), wrap_text=True)
        prepared["output"] = _to_json_str(step_dict.get("output"), wrap_text=True)
        prepared["metadata"] = _to_dict(step_dict.get("metadata"))
        return prepared

    async def create_step(self, step_dict: StepDict):
        prepared = self._prepare_step(step_dict)
        return await super().create_step(prepared)

    async def update_step(self, step_dict: StepDict):
        prepared = self._prepare_step(step_dict)
        return await super().update_step(prepared)

    def _convert_step_row_to_dict(self, row: Dict) -> StepDict:
        step = super()._convert_step_row_to_dict(row)
        step["input"] = _unwrap_for_display(step.get("input"))
        step["output"] = _unwrap_for_display(step.get("output"))
        return step


def _unwrap_for_display(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except Exception:
            return _normalize_display_text(text)
        return _unwrap_for_display(parsed)
    if isinstance(value, dict):
        for key in ("text", "message", "content", "value", "prompt"):
            content = value.get(key)
            if isinstance(content, str) and content.strip():
                return _normalize_display_text(content)
            if isinstance(content, (dict, list)):
                nested = _unwrap_for_display(content)
                if isinstance(nested, str) and nested.strip():
                    return nested
        return value
    if isinstance(value, list):
        lines = []
        for item in value:
            nested = _unwrap_for_display(item)
            if isinstance(nested, str) and nested.strip():
                lines.append(nested)
        if lines:
            return "\n\n".join(lines)
        return value
    return value


def _normalize_display_text(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
        .replace("\\t", "\t")
    )
