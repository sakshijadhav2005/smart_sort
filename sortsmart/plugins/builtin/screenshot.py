import re

from sortsmart.plugins import Detector

PATTERN = re.compile(r"screen\s?shot|screen[_ -]?capture|^snip|^capture", re.IGNORECASE)


class ScreenshotDetector(Detector):
    name = "screenshot"

    def matches(self, file):
        return file.type in ("png", "jpg", "webp") and bool(PATTERN.search(file.name))

    def destination(self, file):
        return "Images/Screenshots"
