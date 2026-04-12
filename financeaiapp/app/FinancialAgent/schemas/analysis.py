"""Structured analysis output schema for LLM with_structured_output."""
from pydantic import BaseModel, Field


class NewsHighlight(BaseModel):
    title: str = Field(description="뉴스 제목")
    source: str = Field(description="출처명 (예: CoinDesk, Reuters)")
    impact: str = Field(description="이 뉴스가 가격에 미치는 영향 한 줄 요약")
    sentiment: str = Field(description="긍정/부정/중립")
    url: str = Field(default="", description="원문 URL (있으면)")
    published_at: str = Field(default="", description="기사 발행일 (YYYY-MM-DD 형식, 뉴스 컨텍스트에서 확인된 경우만)")


class AnalysisResult(BaseModel):
    market_summary: str = Field(
        description="현재 가격, 변동률, 일중 범위를 포함한 시세 요약 (2~3문장)"
    )
    sentiment_overview: str = Field(
        description="뉴스 전반의 시장 심리 요약 — 긍정/부정/중립 비율과 주요 톤 (1~2문장)"
    )
    news_highlights: list[NewsHighlight] = Field(
        default_factory=list,
        description="가격에 가장 영향력 있는 주요 뉴스 3~5개",
        max_length=5,
    )
    risk_factors: list[str] = Field(
        default_factory=list,
        description="주의해야 할 리스크 요인 2~4개",
        max_length=4,
    )
    outlook: str = Field(
        description="단기 방향성 판단과 근거 (1~2문장, 매매 권유 금지)"
    )
    related_tickers: list[str] = Field(
        default_factory=list,
        description="분석 종목과 연관된 다른 종목 3~5개 (예: BTC 분석 시 ETH, SOL, COIN)",
        max_length=5,
    )
