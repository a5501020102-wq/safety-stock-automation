"""
Convert SAP Material Master Excel to material_master.json.

Usage:
    python convert_master.py <input.xlsx> [output.json]

Reads the SAP material list (columns: 物料, 物料群組, 物料說明, 物料類型, 工廠)
and produces a structured JSON with:
  - categories: grouped by material-group prefix (~20 categories)
  - mapping: SKU → group_id (38k+ entries)

Run this when the material master is updated (typically quarterly).
"""
import json
import sys
from pathlib import Path

import pandas as pd


def convert(input_path: str, output_path: str | None = None) -> dict:
    df = pd.read_excel(input_path)

    required = {"物料", "物料群組"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}. Found: {list(df.columns)}")

    df = df.dropna(subset=["物料", "物料群組"]).copy()
    df["物料"] = df["物料"].astype(str).str.strip()
    df["物料群組"] = df["物料群組"].astype(str).str.strip()
    if "物料說明" in df.columns:
        df["物料說明"] = df["物料說明"].fillna("").astype(str).str.strip()

    # Build mapping: sku → group_id
    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        sku = row["物料"]
        group = row["物料群組"]
        if sku and group and group != "nan":
            mapping[sku] = group

    # Build categories: group prefix → { name, groups }
    group_counts: dict[str, int] = {}
    group_names: dict[str, str] = {}
    for _, row in df.iterrows():
        group = str(row["物料群組"])
        if group == "nan":
            continue
        group_counts[group] = group_counts.get(group, 0) + 1
        if group not in group_names and "物料說明" in df.columns:
            group_names[group] = str(row["物料說明"])[:60]

    categories: dict[str, dict] = {}
    for group_id, count in sorted(group_counts.items()):
        prefix = group_id.split("-")[0] if "-" in group_id else group_id
        if prefix not in categories:
            categories[prefix] = {
                "name": _derive_category_name(prefix, group_id),
                "totalCount": 0,
                "groups": {},
            }
        categories[prefix]["groups"][group_id] = {
            "name": group_names.get(group_id, group_id),
            "count": count,
        }
        categories[prefix]["totalCount"] += count

    result = {
        "version": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "totalSkus": len(mapping),
        "totalCategories": len(categories),
        "totalGroups": len(group_counts),
        "categories": categories,
        "mapping": mapping,
    }

    if output_path is None:
        output_path = str(Path(input_path).parent / "material_master.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=None, separators=(",", ":"))

    size_kb = Path(output_path).stat().st_size / 1024
    print(f"Converted: {len(mapping)} SKUs, {len(categories)} categories, "
          f"{len(group_counts)} groups -> {output_path} ({size_kb:.0f} KB)")

    return result


# Well-known category prefixes from SAP product hierarchy
_CATEGORY_NAMES = {
    "15105": "Steel Pipes & Fittings",
    "15223": "Stainless Steel",
    "15110": "Valves & Hardware",
    "15060": "Fasteners",
    "15107": "PVC Grey Pipes",
    "16133": "Wiring Devices",
    "16120": "Wire & Cable",
    "15151": "PVC Orange Pipes",
    "16132": "EMT Conduit",
    "SERVICE": "Services",
    "10800": "Ventilation",
    "11500": "Tools",
    "16400": "Switches & Panels",
    "16137": "Cable Trays",
    "09910": "Steel Plates",
    "15072": "Flex Connectors",
    "06400": "Plywood",
    "16061": "Grounding",
    "16500": "Valves (Bronze)",
    "15080": "Duct Tape & Sealing",
}


def _derive_category_name(prefix: str, sample_group: str) -> str:
    return _CATEGORY_NAMES.get(prefix, prefix)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_master.py <input.xlsx> [output.json]")
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    convert(inp, out)
