import json
from datetime import datetime, timedelta

import requests


class TommyClient:

    BASE_URL = "https://public.tommbookingsupport.nl"
    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    def __init__(self, api_token):
        self.api_token = api_token

    def _get_headers(self):
        headers = self.HEADERS.copy()
        headers.update({"X-Api-Token": self.api_token,})
        return headers

    @staticmethod
    def _standardize_response_keys(response_json: dict) -> dict:
        for key in list(response_json.keys()):
            new_key = key.replace("-", "_")
            if key != new_key:
                response_json[new_key] = response_json[key]
                del response_json[key]
        return response_json

    def _get_from_tommy(self,
                        endpoint: str,
                        search_params: dict | None =None) -> dict | None:
        headers = self._get_headers()
        response = requests.get(f"{self.BASE_URL}/{endpoint}", headers=headers, params=search_params, timeout=15)
        if response.status_code == 200:
            response_json = response.json().get("data")
            if isinstance(response_json, dict):
                return self._standardize_response_keys(response_json)
            return response_json
        return None

    def get_metadata(self) -> dict | None:
        return self._get_from_tommy("widget/metadata", search_params={
            "data": "age-categories|accommodation-groups"
        })

    def get_accommodations(self) -> dict | None:
        metadata = self._get_from_tommy("widget/metadata", search_params={"data": "accommodations"})
        if metadata:
            return metadata.get("accommodations")
        return None

    def get_availability(self,
                         arrival_date: str,
                         departure_date: str,
                         age_categories: str | None,
                         accommodation_groups: str | None = None) -> dict | None:
        def expand_date_ranges(params):
            fmt = "%Y-%m-%d"
            for key in ["date-from", "date-till"]:
                ranges = []
                if key in params:
                    date = datetime.strptime(params[key], fmt)
                    prev_day = (date - timedelta(1)).strftime(fmt)
                    next_day = (date + timedelta(1)).strftime(fmt)
                    ranges.extend([prev_day, params[key], next_day])
                params[key] = "|".join(ranges)
            return params

        params = {"date-from": arrival_date, "date-till": departure_date}
        params = expand_date_ranges(params)

        if accommodation_groups:
            params["accommodation-group"] = accommodation_groups

        if age_categories:
            try:
                age_categories_params = []
                for age_category, pax in age_categories.items():
                    age_categories_params[age_category] = int(age_category["id"])
                params["age-category"] = json.dumps(age_categories)
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        else:
            return None

        accommodations = self._get_from_tommy("widget/search", params)
        if accommodations:
            return accommodations

        return None
