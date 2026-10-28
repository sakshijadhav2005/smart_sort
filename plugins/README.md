# plugins/

Drop `*.py` files here; SortSmart loads every `Detector` and `Action`
subclass it finds at startup. Files starting with `_` are skipped.

```python
from sortsmart.plugins import Detector

class InvoiceDetector(Detector):
    name = "invoice"

    def matches(self, file):
        return file.type == "pdf" and "invoice" in file.text.lower()

    def destination(self, file):
        return "Documents/Invoices"
```

A plugin that raises is disabled and logged; sorting continues. Plugins run
with full Python access, so only install plugins you trust.
