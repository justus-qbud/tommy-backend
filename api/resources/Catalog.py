import json
import os
import re
import unicodedata

from flask import request
from flask_restful import Resource

from api.common.cache import redis_cache
from api.common.parser.ai import ParserAI
from api.common.parser.rules import ParserRules
from api.common.response import TommyResponse, TommyErrors
from api.common.tommy.client import TommyClient


class Catalog(Resource):

    @staticmethod
    def validate_catalog_id(catalog_id):
        return catalog_id == "219b2fc6-d2e0-42e9-a670-848124341c0f"

    @staticmethod
    def extract_language_from_metadata_item_name(metadata_item, language: str = "nl") -> dict:
        options = {}
        for metadata_option in metadata_item:
            for language_item in metadata_option.get("name"):
                if language_item.get("language") == language:
                    options[metadata_option.get("id")] = language_item.get("value")
                break
        return options

    @staticmethod
    def extract_language_from_metadata_item(metadata_item: list[dict], metadata_keys: list, language: str = "nl") -> dict[int, dict]:
        options = {}
        for metadata_option in metadata_item:
            option = {}
            for key in metadata_keys:
                for language_item in metadata_option.get(key):
                    if language_item.get("language") == language:
                        option[key] = language_item.get("value")
                    break
            options[metadata_option.get("id")] = option
        return options

    @redis_cache("catalog:{catalog_id}:filters", ex=3600)
    def get_catalog_filters_from_tommy(self, catalog_id: str):
        # TODO: map catalog_id to TOMMY_API_KEY
        client = TommyClient(os.getenv("TOMMY_API_KEY_TEMP"))
        tommy_metadata = client.get_metadata()
        catalog_filters = {}
        if tommy_metadata:
            for key in tommy_metadata:
                catalog_filters[key] = self.extract_language_from_metadata_item_name(tommy_metadata[key])
        return catalog_filters

    def get(self, catalog_id):
        if not self.validate_catalog_id(catalog_id):
            return TommyErrors.bad_request()

        catalog_filters = self.get_catalog_filters_from_tommy(catalog_id)

        return TommyResponse.success(data={
            "filters": catalog_filters
        })


class CatalogSearch(Resource):

    REGEX_ALPHANUMERIC = re.compile(r"[a-z\d]")
    REGEX_DOUBLE_SPACES = re.compile(r"\s{2,}")
    REGEX_INVALID_CHARS = re.compile(r"[^A-Za-z0-9,.\-/\s]+")
    REGEX_MONTH_PATTERN = re.compile(
        r"\b(?P<jan>jan(uar[iy]?|vier))|(?P<feb>feb(ruar[iy]?|braio))|(?P<mar>maa?r(zo?|s|t)|märz)|(?P<apr>apr(il[e]?))|(?P<may>ma[iy]|maggio|mei)|(?P<jun>jun[ei]|giu[gn]no?)|(?P<jul>jul(y|i[oa]?))|(?P<aug>au?g(ust(us|o)?)?|août|aout)|(?P<sep>sep(tember|tembre)?)|(?P<oct>o[ck]t(ober|obre)?)|(?P<nov>nov(ember|embre)?)|(?P<dec>de[cz](ember|embre|icembre)?)\b"
    )

    @staticmethod
    def _validate_user_query(user_query):
        return user_query != "" and 100 > len(user_query) >= 5

    def _sanitize_user_query(self, user_query):
        def get_month(match):
            months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            for i, month in enumerate(months):
                if match.group(month):
                    return month
            return match.group(0)

        def remove_accents(text):
            normalized = unicodedata.normalize("NFD", text)
            ascii_text = ''.join(c for c in normalized if unicodedata.category(c) != "Mn")
            return ascii_text

        user_query = user_query.lower().strip()
        user_query = remove_accents(user_query)
        user_query = self.REGEX_INVALID_CHARS.sub("", user_query)
        user_query = self.REGEX_MONTH_PATTERN.sub(get_month, user_query)
        user_query = self.REGEX_DOUBLE_SPACES.sub(" ", user_query)
        return user_query

    @staticmethod
    def get_catalog_results_from_tommy(
        arrival_date: str,
        departure_date: str,
        age_categories: dict | None,
        accommodation_groups: list[str] | None = None,
    ) -> list:
        if not arrival_date or not departure_date or not age_categories:
            return []
        client = TommyClient(os.getenv("TOMMY_API_KEY_TEMP"))
        availability = client.get_availability(
            arrival_date=arrival_date,
            departure_date=departure_date,
            age_categories=age_categories,
            accommodation_groups="|".join(accommodation_groups) if accommodation_groups else None,
        )
        return availability or []

    @staticmethod
    def get_accommodations_from_tommy() -> dict:
        client = TommyClient(os.getenv("TOMMY_API_KEY_TEMP"))
        tommy_accommodations = client.get_accommodations()
        accommodations = Catalog.extract_language_from_metadata_item(tommy_accommodations, ["name", "url"])
        for accommodation in tommy_accommodations:
            accommodations[accommodation.get("id")]["image_url"] = accommodation.get("images" , [{}])[0].get("original")
        return accommodations or dict()

    @staticmethod
    @redis_cache("catalog:{catalog_id}:query:{user_query}:parse", ex=3600)
    def _parse_user_query(catalog_id, user_query, catalog_filters) -> dict:
        parser_rules = ParserRules()
        parse, user_query = parser_rules.parse(user_query, catalog_filters)
        if user_query and CatalogSearch.REGEX_ALPHANUMERIC.search(user_query) is not None:
            parser_ai = ParserAI()
            parse_ai = parser_ai.parse(user_query, json.dumps(catalog_filters), catalog_id)
            for key in parse_ai:
                if key not in parse:
                    parse[key] = parse_ai[key]
        return parse

    def get(self, catalog_id):
        user_query = request.args.get("q")
        if not Catalog.validate_catalog_id(catalog_id) or not self._validate_user_query(user_query):
            return TommyErrors.bad_request()
        user_query = self._sanitize_user_query(user_query)

        catalog_filters = Catalog().get_catalog_filters_from_tommy(catalog_id)
        accommodations = self.get_accommodations_from_tommy()
        parse = self._parse_user_query(catalog_id, user_query, catalog_filters)
        results = self.get_catalog_results_from_tommy(
            parse.get("dates", {}).get("start"),
            parse.get("dates", {}).get("end"),
            parse.get("age_categories"),
            parse.get("accommodations"),
        )
        for result in results:
            if result.get("id") in accommodations:
                result.update(accommodations[result.get("id")])

        return TommyResponse.success(data={"parse": parse, "results": results})