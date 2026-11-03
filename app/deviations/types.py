"""Pydantic models for deviation extraction state."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScrapedDetail(BaseModel):
    record_id: str | None = None
    record_url: str | None = None
    description: str | None = None
    property_value: str | None = None
    loan_amount: str | None = None
    tenure: str | None = None
    emi: str | None = None
    requested_roi: str | None = None
    ideal_roi: str | None = None
    updated_roi: str | None = None
    requested_variance: str | None = None
    page_refs: list[dict[str, str]] = Field(default_factory=list)
    opportunity_url: str | None = None
    cl_contract_url: str | None = None
    collateral_url: str | None = None
    lms2_collateral_url: str | None = None
    lms2_cl_contract_url: str | None = None
    skip: bool = False
    skip_reason: str | None = None


class DetailEntry(BaseModel):
    value: str = ""
    det: ScrapedDetail = Field(default_factory=ScrapedDetail)
    refs: list[dict[str, str]] = Field(default_factory=list)
    skip: bool = False
    skip_reason: str | None = None
    opportunity_url: str | None = None
    cl_contract_url: str | None = None
    collateral_url: str | None = None
    lms2_collateral_url: str | None = None
    lms2_cl_contract_url: str | None = None
    opportunity_product_type: str | None = None


class State(BaseModel):
    numbers: set[str] = Field(default_factory=set)
    total: int | None = None
    links: dict[str, str] = Field(default_factory=dict)
    approval_dates: dict[str, str] = Field(default_factory=dict)
    details: list[DetailEntry] = Field(default_factory=list)
    refs: list[dict[str, str]] = Field(default_factory=list)
    skip_reason: str | None = None
    skipped: int = 0
    failed: int = 0
    product_cache: dict[str, str | None] = Field(default_factory=dict, alias="_product_cache")

    model_config = {"populate_by_name": True}
