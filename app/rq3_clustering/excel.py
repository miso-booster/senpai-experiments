from pathlib import Path

import pandas as pd


def save_outputs(
    out_dir: Path,
    architecture_tables: dict[str, pd.DataFrame],
    inventory: pd.DataFrame,
    duplicates: pd.DataFrame,
    export_csvs: bool,
) -> list[Path]:
    """Write one workbook per architecture plus an optional CSV export set."""
    out_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    for arch_id, table in architecture_tables.items():
        workbook_path = out_dir / f"{arch_id}_answer_clustering.xlsx"
        with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
            table.to_excel(writer, sheet_name="answers_matrix")
            arch_inventory = inventory[inventory["arch_id"] == arch_id].copy()
            arch_inventory.to_excel(writer, index=False, sheet_name="inventory")
            if not duplicates.empty:
                arch_duplicates = duplicates[duplicates["arch_id"] == arch_id].copy()
                if not arch_duplicates.empty:
                    arch_duplicates.to_excel(writer, index=False, sheet_name="duplicates")
        written_paths.append(workbook_path)

        if export_csvs:
            table.to_csv(out_dir / f"{arch_id}_answer_clustering.csv", encoding="utf-8")
            inventory[inventory["arch_id"] == arch_id].to_csv(
                out_dir / f"{arch_id}_inventory.csv",
                index=False,
                encoding="utf-8",
            )
            if not duplicates.empty:
                arch_duplicates = duplicates[duplicates["arch_id"] == arch_id]
                if not arch_duplicates.empty:
                    arch_duplicates.to_csv(
                        out_dir / f"{arch_id}_duplicates.csv",
                        index=False,
                        encoding="utf-8",
                    )

    manifest_path = out_dir / "RQ3_clustering_manifest.xlsx"
    with pd.ExcelWriter(manifest_path, engine="openpyxl") as writer:
        inventory.to_excel(writer, index=False, sheet_name="inventory")
        if not duplicates.empty:
            duplicates.to_excel(writer, index=False, sheet_name="duplicates")
        pd.DataFrame(
            [{"arch_id": arch_id, "rows": len(table), "columns": len(table.columns)} for arch_id, table in architecture_tables.items()]
        ).to_excel(writer, index=False, sheet_name="architectures")
    written_paths.append(manifest_path)

    return written_paths
