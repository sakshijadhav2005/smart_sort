"""Streamlit dashboard (FR14): ``sortsmart dashboard`` or
``streamlit run sortsmart/dashboard.py``. Reads the catalog; moves nothing."""
import os

import streamlit as st

from sortsmart import Sorter


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


@st.cache_resource
def get_sorter():
    return Sorter(os.environ.get("SORTSMART_CONFIG"))


st.set_page_config(page_title="SortSmart", layout="wide")
sorter = get_sorter()
stats = sorter.stats()
health = sorter.health()

st.title("SortSmart")
st.caption(f"Catalog: {sorter.config.catalog_path} · Health: {health['status']}")
for problem in health["problems"]:
    st.warning(problem)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Files processed", stats["total"])
c2.metric("Storage sorted", human(stats["storage_bytes"]))
c3.metric("Space saved by de-duplication", human(stats["duplicates"]["space_saved_bytes"]),
          f"{stats['duplicates']['count']} duplicates", delta_color="off")
c4.metric("In quarantine", stats["quarantine"]["count"])

left, right = st.columns(2)
with left:
    st.subheader("Storage by category")
    total = stats["storage_bytes"] or 1
    st.dataframe(
        [{"Category": k, "Files": v["count"], "Size": human(v["bytes"]),
          "Share": v["bytes"] / total} for k, v in stats["by_category"].items()],
        column_config={"Share": st.column_config.ProgressColumn(format="percent", min_value=0,
                                                                max_value=1)},
        hide_index=True, width="stretch")
with right:
    st.subheader("Quarantine")
    rows = sorter.search(status="quarantined", restored=False, limit=200)
    st.dataframe([{"ID": r["id"], "File": r["name"], "Reason": r["reason"],
                   "When": r["created_at"]} for r in rows],
                 hide_index=True, width="stretch")

st.subheader("Recent activity")
st.dataframe([{"ID": r["id"], "Status": r["status"], "Type": r["type"], "File": r["name"],
               "Moved to": r["new_path"], "Restored": bool(r["restored_at"]),
               "When": r["created_at"]} for r in sorter.search(limit=100)],
             hide_index=True, width="stretch")
