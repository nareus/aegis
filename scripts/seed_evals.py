"""Mirror YAML golden cases from evals/*/cases/*.yaml into eval_golden_cases.

The YAML files are the source of truth. The DB mirror exists so you can
join eval results against case metadata in SQL. Re-run after edits.

Usage:
    uv run python scripts/seed_evals.py
"""

import asyncio
import json
import sys
from pathlib import Path

import yaml

from aegis.db.engine import close_pool, get_pool

EVALS_DIR = Path(__file__).resolve().parent.parent / "evals"


async def seed_one(pool, case_file: Path) -> tuple[str, str]:
    case = yaml.safe_load(case_file.read_text())

    for required in ("case_id", "eval_name", "input", "expected"):
        if required not in case:
            raise ValueError(f"{case_file}: missing required key '{required}'")

    eval_name = case["eval_name"]
    expected_dir = EVALS_DIR / eval_name / "cases"
    if case_file.parent.resolve() != expected_dir.resolve():
        raise ValueError(
            f"{case_file}: eval_name '{eval_name}' does not match its directory"
        )

    await pool.execute(
        """
        INSERT INTO eval_golden_cases
            (eval_name, case_id, input_payload, expected_output, notes)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
        ON CONFLICT (eval_name, case_id) DO UPDATE
        SET input_payload   = EXCLUDED.input_payload,
            expected_output = EXCLUDED.expected_output,
            notes           = EXCLUDED.notes
        """,
        eval_name,
        case["case_id"],
        json.dumps(case["input"]),
        json.dumps(case["expected"]),
        case.get("notes"),
    )
    return eval_name, case["case_id"]


async def main() -> int:
    if not EVALS_DIR.exists():
        print(f"no evals directory at {EVALS_DIR}", file=sys.stderr)
        return 1

    case_files = sorted(EVALS_DIR.glob("*/cases/*.yaml"))
    if not case_files:
        print(f"no case files found under {EVALS_DIR}/*/cases/*.yaml", file=sys.stderr)
        return 1

    pool = await get_pool()
    try:
        for case_file in case_files:
            eval_name, case_id = await seed_one(pool, case_file)
            print(f"seeded {eval_name}/{case_id}")
    finally:
        await close_pool()
    print(f"\n{len(case_files)} cases seeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
