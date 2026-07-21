from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ingestion.http_client import NcbiClient

MEDGEN_CUI_PATTERN = re.compile(r"MedGen:(CN?\d+)")


def extract_medgen_cuis(phenotype_ids_field: str) -> list[str]:
    """Extrait les CUI MedGen uniques (dans l'ordre d'apparition) d'un champ PhenotypeIDS."""
    seen: list[str] = []
    for cui in MEDGEN_CUI_PATTERN.findall(phenotype_ids_field or ""):
        if cui not in seen:
            seen.append(cui)
    return seen


def fetch_medgen_concept(client: NcbiClient, cui: str) -> dict:
    """Récupère un concept MedGen à partir d'un CUI (esearch [conceptid] puis esummary)."""
    uids = client.esearch(db="medgen", term=f"{cui}[conceptid]")
    if not uids:
        return {}
    return client.esummary(db="medgen", uid=uids[0])


def parse_medgen_conceptmeta(conceptmeta: str) -> dict:
    """Extrait mim_number, mode_inheritance, clinical_summary et hpo_terms du XML conceptmeta."""
    root = ET.fromstring(f"<root>{conceptmeta}</root>")

    mim = root.find(".//OMIM/MIM")
    inheritance = root.find(".//ModeOfInheritance/Name")
    definition = root.find(".//Definition")

    hpo_terms = [
        {"hpo_id": cf.get("SDUI"), "hpo_name": cf.findtext("Name", "")}
        for cf in root.findall(".//ClinicalFeature")
        if cf.get("SDUI", "").startswith("HP:")
    ]

    return {
        "mim_number": mim.text if mim is not None else "",
        "mode_inheritance": inheritance.text if inheritance is not None else "",
        "clinical_summary": definition.text if definition is not None else "",
        "hpo_terms": hpo_terms,
    }
