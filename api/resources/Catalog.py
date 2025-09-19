import json
import os
import re

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
    def _extract_language_from_metadata_item(metadata_item, language: str = "nl"):
        options = []
        for metadata_option in metadata_item:
            for language_item in metadata_option.get("name"):
                if language_item.get("language") == language:
                    options.append(language_item.get("value"))
                break
        return options

    @redis_cache("catalog:{catalog_id}:filters", ex=3600)
    def get_catalog_filters_from_tommy(self, catalog_id: str):
        # TODO: map catalog_id to TOMMY_API_KEY
        client = TommyClient(os.getenv("TOMMY_API_KEY_TEMP"))
        tommy_metadata = client.get_metadata()
        catalog_filters = {}
        if tommy_metadata:
            for key in tommy_metadata:
                catalog_filters[key] = self._extract_language_from_metadata_item(tommy_metadata[key])
        return catalog_filters

    def get(self, catalog_id):
        if not self.validate_catalog_id(catalog_id):
            return TommyErrors.bad_request()

        catalog_filters = self.get_catalog_filters_from_tommy(catalog_id)

        return TommyResponse.success(data={
            "filters": catalog_filters
        })


class CatalogSearch(Resource):

    REGEX_DOUBLE_SPACES = re.compile(r"\s{2,}")
    REGEX_INVALID_CHARS = re.compile(r"[^A-Za-z0-9,.-/\s]+")
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

        user_query = user_query.lower().strip()
        user_query = self.REGEX_INVALID_CHARS.sub("", user_query)
        user_query = self.REGEX_MONTH_PATTERN.sub(get_month, user_query)
        user_query = self.REGEX_DOUBLE_SPACES.sub(" ", user_query)
        return user_query

    @staticmethod
    @redis_cache("catalog:{catalog_id}:query:{user_query}:parse", ex=3600)
    def _parse_user_query(catalog_id, user_query, catalog_filters) -> dict:
        parser_rules = ParserRules()
        parse, user_query = parser_rules.parse(user_query)
        if user_query:
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
        parse = self._parse_user_query(catalog_id, user_query, catalog_filters)

        try:
            return TommyResponse.success(data={
                "parse": parse,
                "results": []
            })
        except (json.decoder.JSONDecodeError, TypeError):
            return TommyErrors.unprocessable_entity()
