"""Writes docs/ml-forecast-contract.schema.json from the Pydantic models. Run: python -m app.forecast.export_schema"""

import json
from pathlib import Path

from app.forecast.contract import contract_schemas

if __name__ == "__main__":
    path = Path(__file__).resolve().parents[3] / "docs" / "ml-forecast-contract.schema.json"
    path.write_text(json.dumps(contract_schemas(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")
