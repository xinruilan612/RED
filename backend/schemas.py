"""Strict transport commands. Domain Run remains the final approval authority."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.contracts import DomainError


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['next', 'edit', 'supplement', 'accept', 'adopt_manual', 'cancel', 'recover', 'repair_review']
    version: int = Field(ge=0)
    key: str = Field(min_length=1, max_length=100)
    payload: dict


class JobCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['start', 'pause', 'step', 'retry_research']
    queries: list[str] | None = None
    version: int = Field(ge=0)
    key: str = Field(min_length=1, max_length=100)


def parse(model, data):
    try:
        return model.model_validate(data).model_dump()
    except ValidationError:
        raise DomainError('INVALID_INPUT', '命令字段或类型无效') from None
