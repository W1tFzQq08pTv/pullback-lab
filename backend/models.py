from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Parameters(BaseModel):
    strategies: list[Literal['trend_pullback','trend_pullback_v2','martin_daily']] = Field(default_factory=lambda:['trend_pullback'], min_length=1,max_length=3)
    v2_mode: Literal['fixed','up','down'] = 'fixed'
    v2_allocation: float = Field(1, gt=0, le=1)
    v2_batches: int = Field(2, ge=1, le=4)
    v2_step: float = Field(.02, gt=0, le=.1)
    v2_fast: int = Field(20, ge=2, le=120)
    v2_middle: int = Field(50, ge=3, le=250)
    v2_slow: int = Field(200, ge=10, le=500)
    v2_slope: int = Field(10, ge=1, le=60)
    v2_pullback: int = Field(5, ge=1, le=30)
    v2_market_filter: bool = True
    martin_risk: float = Field(.005,gt=0,le=.05)
    martin_max_stop: float = Field(.03,gt=0,le=.1)
    martin_min_return: float = Field(.3,ge=0,le=3)
    martin_min_turnover: float = Field(20000000,ge=0,le=1e11)
    martin_support_tolerance: float = Field(.015,ge=0,le=.05)
    martin_anchor_window: int = Field(63,ge=21,le=126)
    martin_pool_id: str | None = None
    symbol: str = Field("002028.SZ", pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    time_range: Literal['all','custom'] = 'custom'
    start: date = date(2016, 10, 12)
    end: date = date(2026, 10, 9)
    fast: int = Field(20, ge=2, le=120)
    middle: int = Field(50, ge=3, le=250)
    slow: int = Field(200, ge=10, le=500)
    slope: int = Field(10, ge=1, le=60)
    pullback: int = Field(5, ge=1, le=30)
    market_filter: bool = True
    capital: float = Field(100000, ge=1000, le=1e8)
    allocation: float = Field(1, gt=0, le=1)
    commission: float = Field(.0003, ge=0, le=.01)
    min_commission: float = Field(5, ge=0, le=100)
    slippage_bps: float = Field(5, ge=0, le=100)
    snapshot_id: str | None = None
    allow_suffix: bool = True
    data_after: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode='after')
    def validate_order(self):
        if len(set(self.strategies))!=len(self.strategies):
            raise ValueError('策略不能重复选择')
        if self.start > self.end:
            raise ValueError('开始日期不能晚于结束日期')
        if not self.fast < self.middle < self.slow:
            raise ValueError('均线周期必须满足短期 < 中期 < 长期')
        if self.start < date(2016, 1, 1):
            raise ValueError('首版费用模型支持2016年起的回测')
        if not self.v2_fast < self.v2_middle < self.v2_slow:
            raise ValueError('v2均线周期必须满足短期 < 中期 < 长期')
        if self.v2_mode != 'fixed' and self.v2_batches < 2:
            raise ValueError('分批模式至少需要两批')
        return self

class SyncRequest(BaseModel):
    symbol: str = Field("002028.SZ", pattern=r"^\d{6}\.(SZ|SH|BJ)$")
    force: bool = False


class CacheBatchRequest(BaseModel):
    symbols: list[str] = Field(min_length=1,max_length=10000)
    concurrency: int = Field(4,ge=1,le=4)
