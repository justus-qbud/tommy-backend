import json
import re
from datetime import datetime


class ParserRules:

    def _parse_dates(self, user_query: str) -> tuple[dict, str] | None:
        parser_dates = ParserDates()
        return parser_dates.parse(user_query)

    def parse(self, user_query: str) -> tuple[dict, str] | None:
        parse = {}
        parse_dates, user_query = self._parse_dates(user_query)
        if parse_dates:
            parse["dates"] = parse_dates
        return parse, user_query


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

    def extract_month_from_text(self, text):
        """Extract month from text like '12 dec' or 'december 12'"""
        text = text.strip().lower()

        # Check for month names in the text
        for month_name, month_num in self.MONTHS.items():
            if month_name in text:
                return month_num
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
        for match in re.finditer(self.RANGE_PATTERN, text.lower()):
            start_text, end_text = match.groups()

            context_month = self.extract_month_from_text(end_text)
            context_year = datetime.now().year

            # Parse start date
            start_date = self.parse_date(start_text, context_year, context_month)
            if not start_date:
                continue

            # Extract context for end date
            start_parts = start_date.split("-")
            context_year = int(start_parts[0])
            context_month = int(start_parts[1])

            # Parse end date with context
            end_date = self.parse_date(end_text, context_year, context_month)
            if not end_date:
                continue

            if remove_from_text:
                text = text[:match.start()] + text[match.end():]
                text = text.strip()

            return {"start": start_date, "end": end_date}, text

        return None, text
