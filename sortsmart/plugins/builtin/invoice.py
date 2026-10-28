from sortsmart.plugins import Detector


class InvoiceDetector(Detector):
    name = "invoice"

    def matches(self, file):
        return file.type == "pdf" and "invoice" in (file.name + " " + file.text).lower()

    def destination(self, file):
        return "Documents/Invoices"
