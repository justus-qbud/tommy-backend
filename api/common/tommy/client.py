import requests


class TommyClient:

    BASE_URL = "https://public.tommytest.nl"
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
        response = requests.get(f"{self.BASE_URL}/{endpoint}", headers=headers, params=search_params)
        if response.status_code == 200:
            response_json = response.json().get("data")
            return self._standardize_response_keys(response_json)
        return None

    def get_metadata(self):
        return self._get_from_tommy("/widget/metadata", search_params={
            "data": "age-categories|accommodation-groups"
        })
