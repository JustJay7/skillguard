"""Freeze authored local cases before the native parser repair conversation."""
from pathlib import Path

from skillguard.evaluation.receipt_contract import freeze, load_frozen, validate_suite

__all__ = ["freeze", "load_frozen", "validate_suite"]


def main() -> None:
    print(freeze(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    main()
