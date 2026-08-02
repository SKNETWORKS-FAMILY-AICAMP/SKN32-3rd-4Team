"""실험실 라우터: 파라미터 실험 / 토큰·비용 / 유즈케이스."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.lab import experiments as X
from app.lab.usecase import run_usecase

router = APIRouter(prefix="/api/lab", tags=["lab"])


class BasicReq(BaseModel):
    prompt: str = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=128, ge=1, le=512)


class RoleReq(BasicReq):
    system: str = Field(min_length=1)


class DiversityReq(BaseModel):
    prompt: str = Field(min_length=1)
    n: int = Field(default=3, ge=1, le=10)
    temperature: float = Field(default=1.0, ge=0, le=2)


class TokenCompareReq(BaseModel):
    ko_text: str = Field(min_length=1)
    en_text: str = Field(min_length=1)


class CostReq(BaseModel):
    prompt_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model: str = Field(min_length=1)


class UsecaseReq(BaseModel):
    task_type: str
    text: str = Field(min_length=1)
    target_lang: str = "영어"


@router.post("/basic")
def basic(body: BasicReq) -> dict:
    return {"answer": X.basic_call(body.prompt, body.temperature, body.max_tokens)}


@router.post("/role")
def role(body: RoleReq) -> dict:
    return {"answer": X.role_call(body.prompt, body.system, body.temperature, body.max_tokens)}


@router.post("/diversity")
def diversity(body: DiversityReq) -> dict:
    return X.diversity(body.prompt, body.n, body.temperature)


@router.post("/token-compare")
def token_compare(body: TokenCompareReq) -> dict:
    return X.token_compare(body.ko_text, body.en_text)


@router.post("/estimate-cost")
def estimate_cost(body: CostReq) -> dict:
    return X.estimate_cost(body.prompt_tokens, body.output_tokens, body.model)


@router.post("/usecase")
def usecase(body: UsecaseReq) -> dict:
    return {"result": run_usecase(body.task_type, body.text, body.target_lang)}
