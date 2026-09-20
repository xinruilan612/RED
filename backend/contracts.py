"""Load the approved contract; no provider SDK or network side effects."""
import json
from pathlib import Path

CONTRACT = json.loads((Path(__file__).resolve().parents[1] / 'docs/design/design_contract.json').read_text())
PARAMETERS = CONTRACT['parameters']


class DomainError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, code, message):
    if not condition:
        raise DomainError(code, message)


def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, 'INVALID_INPUT', name)
    return value


def tool_allowed(agent, tool, runtime_allowed, resource_owner, caller_owner):
    """Resource ownership must come from the repository, never model arguments."""
    require(resource_owner == caller_owner, 'RESOURCE_NOT_FOUND', '资源不可访问')
    allowed = CONTRACT['tool_permissions'].get(agent, [])
    require(tool in allowed and tool in runtime_allowed, 'TOOL_FORBIDDEN', '未授权工具')
    require(tool not in CONTRACT['disabled_tools_default'], 'TOOL_DISABLED', '公开检索尚未启用')


def legacy_candidate(record):
    """Read-only import envelope; legacy completed is never accepted/approved."""
    require(isinstance(record, dict), 'INVALID_INPUT', '旧记录须为对象')
    return {'schema_version': 2, 'legacy_schema_version': 1,
            'status': 'needs_review', 'accepted': False,
            'legacy_candidate': json.loads(json.dumps(record)),
            'review_ref': None, 'confirmation': None}
