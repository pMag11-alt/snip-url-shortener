from pydantic import BaseModel, Field, HttpUrl


class LinkCreate(BaseModel):
    url: HttpUrl = Field(description="The long URL to shorten (http or https).")
    alias: str | None = Field(default=None, description="Optional custom short code.")
    expires_in_days: int | None = Field(default=None, ge=1, le=365, description="Optional expiry, in days.")

    model_config = {
        "json_schema_extra": {
            "examples": [{"url": "https://github.com/fastapi/fastapi", "alias": "fastapi", "expires_in_days": 30}]
        }
    }


class Link(BaseModel):
    code: str
    short_url: str
    target_url: str
    created_at: str
    expires_at: str | None
    clicks: int


class Count(BaseModel):
    label: str
    clicks: int


class DailyCount(BaseModel):
    date: str
    clicks: int


class LinkStats(BaseModel):
    code: str
    target_url: str
    total_clicks: int
    last_7_days: list[DailyCount]
    referrers: list[Count]
    browsers: list[Count]
    devices: list[Count]
