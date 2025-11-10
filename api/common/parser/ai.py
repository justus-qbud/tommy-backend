import json
from datetime import date
from typing import Dict, Optional

from openai import OpenAI
from pydantic import BaseModel, Field



class DateRange(BaseModel):
    start: date = Field(description="Start date in YYYY-MM-DD")
    end: date = Field(description="End date in YYYY-MM-DD")


class SearchFilters(BaseModel):
    accommodation_groups: Optional[list[str]] = Field(
        None,
        alias="accommodation-groups",
        description="List of accommodation group IDs"
    )
    amenities: Optional[list[str]] = Field(
        None,
        alias="amenities",
        description="List of amenity IDs, only use if mentioned in user query."
    )
    age_categories: Optional[Dict[str, int]] = Field(
        None,
        description="Map of age category IDs to number of people."
    )
    dates: Optional[DateRange] = Field(
        None,
        description="Date range. Infer from user query if necessary. A weekend runs from Friday to Monday."
    )


class ParserAI:

    MODEL_VERSION = "gpt-5-mini"
    SYSTEM_PROMPT = """
        Based on user query, extract filter options. 
        Besides "dates" (today (minimum) is '{current_date}'), the following filters are available:
    """

    def _get_system_prompt(self, filters: str):
        current_date = date.today()
        return self.SYSTEM_PROMPT.format(current_date=current_date.isoformat()) + filters

    def parse(self, user_query: str, filters: str, catalog_id: str) -> dict:
        client = OpenAI()
        system_prompt = self._get_system_prompt(filters)
        messages = [
            {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "text", "text": user_query}]}
        ]
        response = client.chat.completions.parse(
            model=self.MODEL_VERSION,
            messages=messages,
            verbosity="low",
            reasoning_effort="minimal",
            prompt_cache_key=catalog_id,
            response_format=SearchFilters
        )
        try:
            return json.loads(response.choices[0].message.content)
        except (json.decoder.JSONDecodeError, TypeError):
            return {}
