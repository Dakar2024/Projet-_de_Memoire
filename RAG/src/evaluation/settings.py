"""Réglages de l'évaluation de la génération (E3a), lus dans
`RAG/experiments/evaluation_e3a.yaml` : juge, candidats, graines, effectifs, seuils, budget.

Le juge vit ici et non dans `RAG/config.yaml` : l'ajouter à `llm.profiles` changerait
l'empreinte de configuration des séries officielles de E2a et en ferait un candidat."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from RAG.src.utils.config import DEFAULT_CONFIG_PATH, LlmProfile, _profile, load_search_config
from RAG.src.utils.errors import RagConfigurationError

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "experiments" / "evaluation_e3a.yaml"
STRATA = ("I", "S", "G", "M")


@dataclass(frozen=True)
class Thresholds:
    faithfulness_min: float
    rejection_max: float
    wrong_abstention_max: float
    kappa_min: float


@dataclass(frozen=True)
class EvaluationSettings:
    judge: LlmProfile
    judge_max_tokens: int
    candidates: tuple[str, ...]
    seed_draw: int
    seed_bootstrap: int
    strata: dict[str, int]
    repeat_questions: int
    passes: int
    sample_size: int
    thresholds: Thresholds
    budget_usd: float
    reserve_per_call_usd: float

    @property
    def total_questions(self) -> int:
        return sum(self.strata.values())


def settings_sha256(path: Path = DEFAULT_SETTINGS_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_settings(path: Path = DEFAULT_SETTINGS_PATH, config_path: Path = DEFAULT_CONFIG_PATH) -> EvaluationSettings:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        judge_raw = raw["judge"]
        thresholds = Thresholds(**{k: float(raw["thresholds"][k]) for k in
                                   ("faithfulness_min", "rejection_max", "wrong_abstention_max", "kappa_min")})
        values = dict(
            judge_max_tokens=int(judge_raw["max_tokens"]),
            candidates=tuple(str(c) for c in raw["candidates"]),
            seed_draw=int(raw["seeds"]["draw"]), seed_bootstrap=int(raw["seeds"]["bootstrap"]),
            strata={name: int(raw["strata"][name]) for name in STRATA},
            repeat_questions=int(raw["repeat_questions"]), passes=int(raw["passes"]),
            sample_size=int(raw["sample_size"]), thresholds=thresholds,
            budget_usd=float(raw["budget_usd"]), reserve_per_call_usd=float(raw["reserve_per_call_usd"]),
        )
        judge_name = str(judge_raw.get("name") or "")
    except (OSError, KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as exc:
        raise RagConfigurationError(f"{path} : réglages E3a illisibles ou incomplets : {exc!r}") from exc
    try:
        judge = _profile(judge_name, judge_raw)
    except RagConfigurationError as exc:
        raise RagConfigurationError(f"{path} : profil du juge invalide ({exc})") from exc
    settings = EvaluationSettings(judge=judge, **values)
    if not judge.name or judge.backend != "openrouter":
        raise RagConfigurationError(f"{path} : le juge doit être nommé et servi par OpenRouter")
    official = load_search_config(config_path).profiles
    unknown = sorted(set(settings.candidates) - set(official))
    if unknown or not settings.candidates:
        raise RagConfigurationError(f"{path} : candidat inconnu de llm.profiles {unknown} "
                                    "(les profils d'essai ne concourent pas)")
    # Pas d'auto-préférence : le juge n'appartient à la famille d'aucun candidat (spec §2, Q3).
    family = judge.model.split("/")[0]
    if family in {official[name].model.split("/")[0] for name in settings.candidates}:
        raise RagConfigurationError(f"{path} : le juge est de la même famille ({family}) qu'un candidat")
    for name, value in vars(thresholds).items():
        if not 0.0 <= value <= 1.0:
            raise RagConfigurationError(f"{path} : seuil {name} hors de [0, 1]")
    if any(n < 0 for n in settings.strata.values()) or settings.total_questions == 0:
        raise RagConfigurationError(f"{path} : effectifs de strates invalides")
    if not 1 <= settings.repeat_questions <= settings.total_questions or settings.passes < 2:
        raise RagConfigurationError(f"{path} : repeat_questions dans [1, nombre de questions], passes ≥ 2")
    if settings.sample_size < 1 or settings.judge_max_tokens < 256:
        raise RagConfigurationError(f"{path} : sample_size ≥ 1 et judge.max_tokens ≥ 256 requis")
    if not 0 < settings.reserve_per_call_usd < settings.budget_usd:
        raise RagConfigurationError(f"{path} : budget_usd doit dépasser reserve_per_call_usd (> 0)")
    return settings
