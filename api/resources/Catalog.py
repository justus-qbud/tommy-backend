import json
import os
import re
import unicodedata
from datetime import date

from cerberus import Validator
from flask import request
from flask_restful import Resource
from urllib.parse import urlencode

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
                if key == "amenities":
                    # TODO: remove ad hoc
                    for amenity_key in list(catalog_filters[key].keys()):
                        if catalog_filters[key][amenity_key] == "Aan het water":
                            catalog_filters[key][amenity_key] = "Gelegen naast een meer of zee"
                        elif catalog_filters[key][amenity_key] == "Aantal slaapkamers":
                            del catalog_filters[key][amenity_key]
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
    REGEX_CONSECUTIVE_CHARS = re.compile(r"(\D)\1{2,}|(\d)\1{3,}")
    REGEX_DOUBLE_SPACES = re.compile(r"\s{2,}")
    REGEX_INVALID_CHARS = re.compile(r"[^a-z\d.\-/\s]+")
    REGEX_MONTH_PATTERN = re.compile(
        r"\b(?P<jan>jan(uar[iy]?|vier))|(?P<feb>feb(ruar[iy]?|braio))|(?P<mar>maa?r(zo?|s|t)|märz)|(?P<apr>apr(il[e]?))|(?P<may>ma[iy]|maggio|mei)|(?P<jun>jun[ei]|giu[gn]no?)|(?P<jul>jul(y|i[oa]?))|(?P<aug>aug(ust(us|o)?)?|août|aout)|(?P<sep>sep(tember|tembre)?)|(?P<oct>o[ck]t(ober|obre)?)|(?P<nov>nov(ember|embre)?)|(?P<dec>de[cz](ember|embre|icembre)?)\b"
    )
    REGEX_RANGE_WORDS = re.compile(r"\s+(tot?(\s*en\s*met)|t/?m|thr(ough|u)|(un)?till?|bis)\s+")

    SCHEMA_USER_PARSE = {
        "dates": {
            "type": "dict",
            "required": False,
            "schema": {
                "start": {
                    "type": "string",
                    "required": True,
                    "regex": r"^\d{4}-\d{2}-\d{2}$"
                },
                "end": {
                    "type": "string",
                    "required": True,
                    "regex": r"^\d{4}-\d{2}-\d{2}$"
                }
            }
        },
        "accommodation_groups": {
            "type": "list",
            "required": False,
            "schema": {
                "type": "integer"
            }
        },
        "amenities": {
            "type": "list",
            "required": False,
            "schema": {
                "type": "integer"
            }
        },
        "age_categories": {
            "type": "dict",
            "required": False,
            "keysrules": {
                "type": "string",
                "regex": r"^\d+$"
            },
            "valuesrules": {
                "type": "integer"
            }
        },
    }

    STOPWORDS_NL = set(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.path.join("..", "data", "stopwords-nl.json")))))

    @staticmethod
    def _validate_user_query(user_query):
        if len(user_query) < 4 or len(user_query) > 100:
            return False

        return True

    @staticmethod
    def _validate_user_parse(user_parse):
        validator = Validator()
        return validator.validate(user_parse, CatalogSearch.SCHEMA_USER_PARSE)

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

        def replace_range_words(text):
            return self.REGEX_RANGE_WORDS.sub(" - ", text)

        def replace_number_words(text):
            """Replace number words (1-10) with digits in English, German, and Dutch."""

            word_to_number = {
                # English
                "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
                # German
                "eins": "1", "zwei": "2", "drei": "3", "vier": "4", "fünf": "5",
                "sechs": "6", "sieben": "7", "acht": "8", "neun": "9", "zehn": "10",
                # Dutch
                "een": "1", "twee": "2", "drie": "3", "vier": "4", "vijf": "5",
                "zes": "6", "zeven": "7", "acht": "8", "negen": "9", "tien": "10"
            }

            pattern = r"\b(" + "|".join(word_to_number.keys()) + r")\b"
            return re.sub(pattern, lambda m: word_to_number[m.group(1).lower()], text)

        user_query = user_query.lower().strip()
        user_query = remove_accents(user_query)
        user_query = replace_number_words(user_query)
        user_query = replace_range_words(user_query)
        user_query = self.REGEX_INVALID_CHARS.sub("", user_query)
        user_query = self.REGEX_MONTH_PATTERN.sub(get_month, user_query)
        user_query = self.REGEX_CONSECUTIVE_CHARS.sub("", user_query)
        user_query = self.REGEX_DOUBLE_SPACES.sub(" ", user_query)

        # Remove stopwords
        words = user_query.split()
        filtered_words = [word for word in words if word not in self.STOPWORDS_NL]
        user_query = " ".join(filtered_words)

        return user_query.strip()

    @staticmethod
    def build_booking_url(slot: dict, age_categories: dict, arrival_date: str, departure_date: str) -> str:
        """Build booking URL with query parameters from slot data."""
        age_category_param = json.dumps([
            {"id": cat_id, "pax": count}
            for cat_id, count in age_categories.items()
        ], separators=(',', ':'))

        params = {
            "age-category": age_category_param,
            "arrival-date": arrival_date,
            "departure-date": departure_date,
            "accommodation": slot.get("id"),
        }

        return f"https://demo.prosuco.nl/zoek-en-boek/boeken?{urlencode(params)}"

    @staticmethod
    def get_catalog_results_from_tommy(
        arrival_date: str,
        departure_date: str,
        age_categories: dict | None,
        accommodation_groups: list[int | str] | None = None,
        amenities: dict[str, str] | None = None,
    ) -> list:
        if not arrival_date or not departure_date or not age_categories:
            return []
        client = TommyClient(os.getenv("TOMMY_API_KEY_TEMP"))
        availability = client.get_availability(
            arrival_date=arrival_date,
            departure_date=departure_date,
            age_categories=age_categories,
            accommodation_groups=",".join([str(x) for x in accommodation_groups]) if accommodation_groups else None,
            amenities=amenities
        )
        if availability:
            for slot in availability:
                slot["url"] = CatalogSearch.build_booking_url(slot, age_categories, arrival_date, departure_date)
        return availability or []

    @staticmethod
    def get_accommodations_from_tommy() -> dict:
        client = TommyClient(os.getenv("TOMMY_API_KEY_TEMP"))
        tommy_accommodations = client.get_accommodations()
        accommodations = Catalog.extract_language_from_metadata_item(tommy_accommodations, ["name", "description"])
        for accommodation in tommy_accommodations:
            accommodations[accommodation.get("id")]["image_url"] = accommodation.get("images" , [{}])[0].get("url")
        return accommodations or dict()

    @staticmethod
    @redis_cache("catalog:{catalog_id}:query:{user_query}:parse", ex=3600)
    def _parse_user_query(catalog_id, user_query, catalog_filters) -> dict:
        parser_rules = ParserRules()
        parse, user_query = parser_rules.parse(user_query, catalog_filters)
        if not catalog_filters.get("amenities") and len(parse) == 3:
            return parse

        if user_query and CatalogSearch.REGEX_ALPHANUMERIC.search(user_query) is not None and len(user_query) >= 5:
            parser_ai = ParserAI()
            parse_ai = parser_ai.parse(user_query, json.dumps(catalog_filters), catalog_id)
            for key in parse_ai:
                if key not in parse:
                    parse[key] = parse_ai[key]

        # check if dates in past
        if dates := parse.get("dates"):
            current_date = date.today().isoformat()
            for key in ["start", "end"]:
                if key in dates:
                    if dates[key] < current_date:
                        parse["error"] = "DATES_PAST"
                        del parse["dates"]
                        break
            if dates["start"] >= dates["end"]:
                parse["error"] = "DATES_ORDER"
                del parse["dates"]

        # ensure no Nones in parse
        for key in list(parse.keys()):
            if parse[key] is None:
                del parse[key]
            elif isinstance(parse[key], list):
                parse[key] = [int(x) if isinstance(x, str) and x.isdigit() else x for x in parse[key]]

        return parse

    def get(self, catalog_id):
        # validate, sanitize, and re-validate user query
        original_user_query = request.args.get("q")
        if not Catalog.validate_catalog_id(catalog_id) or not self._validate_user_query(original_user_query):
            return TommyErrors.bad_request()
        user_query = self._sanitize_user_query(original_user_query)
        if not self._validate_user_query(user_query):
            return TommyErrors.bad_request()

        # validate parse
        user_parse = {}
        if request.args.get("parse"):
            try:
                user_parse = json.loads(request.args.get("parse"))
                if user_parse and not self._validate_user_parse(user_parse):
                    return TommyErrors.bad_request()
            except (json.JSONDecodeError, TypeError):
                user_parse = {}

        # parse query
        catalog_filters = Catalog().get_catalog_filters_from_tommy(catalog_id)
        accommodations = self.get_accommodations_from_tommy()
        parse = self._parse_user_query(catalog_id, user_query, catalog_filters)

        # add user parse
        for key in parse:
            if key in user_parse:
                del user_parse[key]
        parse = parse | user_parse

        # search results
        results = None
        if not parse.get("error") and parse.get("dates"):
            results = self.get_catalog_results_from_tommy(
                parse.get("dates", {}).get("start"),
                parse.get("dates", {}).get("end"),
                parse.get("age_categories"),
                parse.get("accommodation_groups"),
                parse.get("amenities")
            )
            if results:
                for result in results:
                    if result.get("id") in accommodations:
                        result.update(accommodations[result.get("id")])

                # sort results based on occurrence
                query_words = original_user_query.split()
                results.sort(
                    key=lambda r: sum(
                        word in unicodedata.normalize('NFD', r.get("name", "").lower()).encode('ascii','ignore').decode('utf-8')
                        for word in query_words
                    ),
                    reverse=True
                )

        return TommyResponse.success(data={"parse": parse, "results": results})