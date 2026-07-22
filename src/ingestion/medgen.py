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

    mim_numbers = [mim.text or "" for mim in root.findall(".//OMIM/MIM")]
    modes_inheritance = [
        name.text or "" for name in root.findall(".//ModeOfInheritance/Name")
    ]
    definitions = [
        {"source": node.get("source", ""), "text": "".join(node.itertext()).strip()}
        for node in root.findall(".//Definition")
    ]

    hpo_terms = [
        {"hpo_id": cf.get("SDUI"), "hpo_name": cf.findtext("Name", "")}
        for cf in root.findall(".//ClinicalFeature")
        if cf.get("SDUI", "").startswith("HP:")
    ]

    return {
        # Champs singuliers : première occurrence, conservés pour compatibilité. Un concept
        # peut porter plusieurs MIM, modes d'hérédité et définitions (beta Thalassemia en a
        # 2, 2 et 7) — les pluriels sont la vue exhaustive.
        "mim_number": mim_numbers[0] if mim_numbers else "",
        "mim_numbers": mim_numbers,
        "mode_inheritance": modes_inheritance[0] if modes_inheritance else "",
        "modes_inheritance": modes_inheritance,
        "clinical_summary": definitions[0]["text"] if definitions else "",
        "definitions": definitions,
        "hpo_terms": hpo_terms,
    }
