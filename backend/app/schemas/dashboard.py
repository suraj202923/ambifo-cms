from pydantic import BaseModel


class DashboardKPIs(BaseModel):
    total_customers: int
    total_leads: int
    open_opportunities: int
    total_mrr: float
    total_arr: float
    customers_added_30d: int


class StatusCount(BaseModel):
    name: str
    color: str
    count: int


class SegmentCount(BaseModel):
    name: str
    count: int


class AssigneeCount(BaseModel):
    name: str
    count: int


class DashboardOut(BaseModel):
    kpis: DashboardKPIs
    by_status: list[StatusCount]
    by_segment: list[SegmentCount]
    by_assignee: list[AssigneeCount]
    recent_history: list  # list of flat dicts
    opportunities_by_month: list[dict]