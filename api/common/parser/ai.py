import json

from openai import OpenAI


class ParserAI:

    MODEL_VERSION = "gpt-5-nano"
    SYSTEM_PROMPT = """
        Based on the user query, extract filter options.
        Return ONLY JSON. Exclude missing keys. 
        # Example 1
        Query: "3 volwassenen"
        Output: {
            "age_categories": {"19834": 3}
        }
        # Example 2
        Query: "huisje voor 2 volwassenen van 30 en 35, 3 tot 12 jan"  
        Output:
        {
            "accommodation-groups": ["98235"]
            "age_categories": {"15325": 2},
            "dates": {
                "start": "2026-01-03",
                "end": "2026-01-12"
            }
        }
        Besides a "date" range, the following filters are available:
    """

    def _get_system_prompt(self, filters: str):
        return self.SYSTEM_PROMPT + filters

    def parse(self, user_query: str, filters: str, catalog_id: str) -> dict:
        client = OpenAI()
        system_prompt = self._get_system_prompt(filters)
        messages = [
            {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "text", "text": user_query}]}
        ]
        response = client.chat.completions.create(
            model=self.MODEL_VERSION,
            messages=messages,
            verbosity="low",
            reasoning_effort="minimal",
            prompt_cache_key=catalog_id
        )
        try:
            return json.loads(response.choices[0].message.content)
        except (json.decoder.JSONDecodeError, TypeError):
            return {}
