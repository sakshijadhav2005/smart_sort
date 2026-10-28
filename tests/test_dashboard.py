import pytest

import samples

pytest.importorskip("streamlit")


def test_dashboard_renders_catalog(sorter, inbox, make_config, workspace, monkeypatch):
    import yaml
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    samples.write(inbox, "png", name="a.png")
    (inbox / "bad.jpg").write_bytes(b"nope")
    sorter.sort_paths([inbox])
    cfg = workspace / "rules.yaml"
    cfg.write_text(yaml.safe_dump(make_config()))
    monkeypatch.setenv("SORTSMART_CONFIG", str(cfg))
    script = Path(__file__).resolve().parents[1] / "sortsmart" / "dashboard.py"
    at = AppTest.from_file(str(script), default_timeout=60).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Files processed"] == "2" and metrics["In quarantine"] == "1"
    assert len(at.dataframe) == 3
