from pathlib import Path
from textwrap import dedent

import pytest


def test_publish_version_check_embedded_python_compiles():
    workflow_path = Path(__file__).parents[1] / ".github" / "workflows" / "publish.yml"
    if not workflow_path.exists():
        pytest.skip("GitHub workflows are not included in the source distribution")

    workflow = workflow_path.read_text(encoding="utf-8")
    marker = "python - <<'PY'\n"
    embedded = workflow.split(marker, 1)[1].split("\n          PY", 1)[0]

    compile(dedent(embedded), str(workflow_path), "exec")
