import re
from datetime import datetime, timedelta


class ParserRules:

    def _parse_dates(self, user_query: str) -> tuple[dict, str] | None:
        parser_dates = ParserDates()
        return parser_dates.parse(user_query)

    def _parse_accommodation_groups(self, user_query: str) -> tuple[list[str], str]:
        parser_accommodation_groups = ParserAccommodationGroups()
        return parser_accommodation_groups.parse(user_query)

    def _parse_age_categories(self, user_query: str) -> tuple[dict[str, int], str]:
        parser_accommodation_groups = ParserAgeCategories()
        return parser_accommodation_groups.parse(user_query)

    def parse(self, user_query: str, catalog_filters: dict) -> tuple[dict, str] | None:
        parse = {}
        parse_dates, user_query = self._parse_dates(user_query)
        if parse_dates:
            parse["dates"] = parse_dates

        parse_accommodation_groups, user_query = self._parse_accommodation_groups(user_query)
        if parse_accommodation_groups:
            accommodation_groups = []
            catalog_filters_accommodation_groups = catalog_filters.get("accommodation_groups", dict())
            for accommodation_group_text in parse_accommodation_groups:
                for key, item in catalog_filters_accommodation_groups.items():
                    if accommodation_group_text in item.lower():
                        accommodation_groups.append(key)
            if accommodation_groups:
                parse["accommodation_groups"] = accommodation_groups

        parse_age_categories, user_query = self._parse_age_categories(user_query)
        if parse_age_categories:
            age_categories = {}
            catalog_filters_age_categories = catalog_filters.get("age_categories", dict())
            for parse_age_category_text, age_category_num in parse_age_categories.items():
                matches = {id_: age_category_text for id_, age_category_text in catalog_filters_age_categories.items() if parse_age_category_text in age_category_text.lower()}
                if len(matches) == 1:
                    age_categories[list(matches.keys())[0]] = age_category_num

            if age_categories:
                parse["age_categories"] = age_categories

        return parse, user_query.strip()


class ParserDates:

    # Step 1: Simple date range detection
    RANGE_PATTERN = r"(\d+(?:\s+\w+)*)\s*(?:tot|t/m|to|through|thru|until|till|bis|[-–—])\s*(\d+(?:\s+\w+)?(?:\s+\d{4})?)"

    # Step 2: Date component patterns
    DATE_PATTERNS = {
        "iso": r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$",
        "numeric": r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$",
        "day_month": r"^(\d{1,2})\s+(\w+)(?:\s+(\d{4}))?$",
        "month_day": r"^(\w+)(?:\s+(\d{1,2}))?(?:\s+(\d{4}))?$",
        "day_only": r"^(\d{1,2})$"
    }

    # Step 3: Month mapping
    MONTHS = {
        "jan": 1, "january": 1, "januari": 1, "januar": 1,
        "feb": 2, "february": 2, "februari": 2, "februar": 2,
        "mar": 3, "march": 3, "maart": 3, "mrt": 3, "mär": 3, "märz": 3,
        "apr": 4, "april": 4,
        "may": 5, "mai": 5, "mei": 5,
        "jun": 6, "june": 6, "juni": 6,
        "jul": 7, "july": 7, "juli": 7,
        "aug": 8, "august": 8, "augustus": 8,
        "sep": 9, "september": 9,
        "oct": 10, "october": 10, "okt": 10, "oktober": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12, "dez": 12, "dezember": 12
    }

    DURATION_PATTERN = r"(\d+)\s*(week|weeks|wk|wks|day|days|d)"

    def extract_month_from_text(self, text):
        """Extract month from text like '12 dec' or 'december 12'"""
        text = text.strip().lower()

        # Check for month names in the text
        for month_name, month_num in self.MONTHS.items():
            if month_name in text:
                return month_num
        return None

    def parse_duration_days(self, text):
        """Convert duration text to number of days"""
        match = re.search(self.DURATION_PATTERN, text.lower())
        if not match:
            return None

        amount = int(match.group(1))
        unit = match.group(2)

        if unit.startswith('week') or unit.startswith('wk'):
            return amount * 7
        elif unit.startswith('day') or unit == 'd':
            return amount
        return None

    def parse_date(self, text, context_year=None, context_month=None):
        """Parse date string to yyyy-mm-dd"""
        text = text.strip().lower()
        year = context_year or datetime.now().year

        # ISO format
        if m := re.match(self.DATE_PATTERNS["iso"], text):
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # Numeric DD/MM/YYYY
        if m := re.match(self.DATE_PATTERNS["numeric"], text):
            y = int(m.group(3))
            if y < 100: y += 2000
            return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

        # Day + Month
        if m := re.match(self.DATE_PATTERNS["day_month"], text):
            day, month_str, year_str = m.groups()
            if month_str in self.MONTHS:
                month = self.MONTHS[month_str]
                if year_str: year = int(year_str)
                return f"{year:04d}-{month:02d}-{int(day):02d}"

        # Month + Day
        if m := re.match(self.DATE_PATTERNS["month_day"], text):
            month_str, day_str, year_str = m.groups()
            if month_str in self.MONTHS:
                month = self.MONTHS[month_str]
                day = int(day_str) if day_str else 1
                if year_str: year = int(year_str)
                return f"{year:04d}-{month:02d}-{day:02d}"

        # Day only (use context)
        if m := re.match(self.DATE_PATTERNS["day_only"], text):
            month = context_month or datetime.now().month
            return f"{year:04d}-{month:02d}-{int(m.group(1)):02d}"

        return None

    def parse(self, text, remove_from_text=True):
        """Extract date ranges as [{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}]"""

        # First check for traditional range pattern
        range_match = re.search(self.RANGE_PATTERN, text.lower())

        if range_match:
            start_text, end_text = range_match.groups()

            end_date = self.parse_date(end_text, datetime.now().year, None)
            if not end_date:
                pass
            else:
                end_parts = end_date.split("-")
                end_year = int(end_parts[0])
                context_month = int(end_parts[1])
                has_explicit_year = bool(re.search(r'\b\d{4}\b', end_text))

                if has_explicit_year:
                    context_year = end_year
                else:
                    context_year = datetime.now().year
                    temp_start = self.parse_date(start_text, context_year, context_month)
                    if temp_start:
                        temp_start_date = datetime.strptime(temp_start, "%Y-%m-%d")
                        if temp_start_date < datetime.now():
                            context_year += 1
                            end_date = self.parse_date(end_text, context_year, None)

                start_date = self.parse_date(start_text, context_year, context_month)
                if not start_date:
                    pass
                else:
                    if remove_from_text:
                        text = text[:range_match.start()] + text[range_match.end():]
                        text = text.strip()
                    return {"start": start_date, "end": end_date}, text

        # Check for date + duration (either order)
        duration_pattern = r"(?:(\d+\s+\w+)\s+(\d+\s*(?:week|weeks|wk|wks|day|days|d))|(\d+\s*(?:week|weeks|wk|wks|day|days|d))\s+(\d+\s+\w+))"
        if duration_match := re.search(duration_pattern, text.lower()):
            if duration_match.group(1):  # date duration
                start_text = duration_match.group(1)
                duration_text = duration_match.group(2)
            else:  # duration date
                start_text = duration_match.group(4)
                duration_text = duration_match.group(3)

            start_date = self.parse_date(start_text)
            duration_days = self.parse_duration_days(duration_text)

            if start_date and duration_days:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                if start_dt < datetime.now():
                    start_dt = start_dt.replace(year=start_dt.year + 1)
                    start_date = start_dt.strftime("%Y-%m-%d")

                end_dt = start_dt + timedelta(days=duration_days - 1)
                end_date = end_dt.strftime("%Y-%m-%d")

                if remove_from_text:
                    text = text[:duration_match.start()] + text[duration_match.end():]
                    text = text.strip()

                return {"start": start_date, "end": end_date}, text

        # Fall back to single date parsing
        single_date = self.parse_date(text)
        if single_date:
            if remove_from_text:
                text = ""
            return {"start": single_date, "end": single_date}, text

        return None, text


class ParserAccommodationGroups:
    # Comprehensive regex patterns for accommodation groups
    PATTERNS = {
        "kamperen": r"\b(kampe(ren|erplek)|camp(site|ground|e(r|n)|ing(platz)?)|zeltplatz)\b",
        "huren": r"\b(huren|(vakantie)?huis|huuraccommodatie|rent|rental|cottage|holiday\s*home|mieten|ferienwohnung|ferienhaus|chalet|bungalow|glampingtent)\b",
        "accommodaties": r"\b(accommodaties|accommodatie|verblijven|accommodations?|lodgings?|unterkünfte|unterkunft|bleibe)\b",
        "toeristenplaatsen": r"\b(toeristenplaatsen|toeristenplaats|tourist\s*spots?|touristenplätze|touristenplatz)\b"
    }

    def parse(self, text, remove_from_text=True) -> tuple[list[str], str]:
        accommodation_groups_texts = []
        working_text = text

        compiled_patterns = {
            dutch_group: re.compile(pattern, re.IGNORECASE)
            for dutch_group, pattern in self.PATTERNS.items()
        }

        for dutch_group, pattern in compiled_patterns.items():
            matches = list(pattern.finditer(working_text))

            if matches:
                accommodation_groups_texts.append(dutch_group)

        return accommodation_groups_texts, working_text if remove_from_text else text


class ParserAgeCategories:
    # Regex patterns for different age categories in multiple languages
    PATTERNS = {
        "volwassenen": re.compile(
            r"\b(\d{1,2})\s+(volwassen(?:en?)?|adults?|erwachsene?)\b"
        ),
        "baby": re.compile(
            r"\b(\d{1,2})\s+(baby's?|babies|babys?)\b"
        ),
        "16+": re.compile(
            r"\b(\d{1,2})\s+(16\+|zestien\+|sixteen\+|sechzehn\+)\b"
        ),
        "18-15": re.compile(
            r"\b(\d{1,2})\s+(18-15|achttien-vijftien|eighteen-fifteen|achtzehn-fünfzehn)\b"
        ),
        "25+": re.compile(
            r"\b(\d{1,2})\s+(25\+|vijfentwintig\+|twenty-five\+|fünfundzwanzig\+)\b"
        ),
        "kinderen": re.compile(
            r"\b(\d{1,2})\s+(kinder(?:en)?|children?|child|kids?)\b"
        )
    }

    def parse(self, text, remove_from_text=True) -> tuple[dict[str, int], str]:
        age_categories = {}
        working_text = text

        for dutch_category, pattern in self.PATTERNS.items():
            matches = list(pattern.finditer(working_text))

            for match in reversed(matches):
                count = int(match.group(1))

                if dutch_category in age_categories:
                    age_categories[dutch_category] += count
                else:
                    age_categories[dutch_category] = count

        return age_categories, working_text if remove_from_text else text
