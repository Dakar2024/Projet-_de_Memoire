import pytest

from RAG.src.utils.diff import SyncPlan, check_deletion_guard, plan_sync
from RAG.src.utils.errors import MassDeletionError

MODEL = "modele@a+onnx:1"


def test_first_indexation_embeds_everything():
    plan = plan_sync({"a": "h1", "b": "h2"}, {}, MODEL)

    assert plan == SyncPlan(to_delete=[], to_embed=["a", "b"], unchanged=0)


def test_identical_index_needs_nothing():
    plan = plan_sync({"a": "h1"}, {"a": ("h1", MODEL)}, MODEL)

    assert plan == SyncPlan(to_delete=[], to_embed=[], unchanged=1)


def test_changed_content_new_document_and_removed_document():
    gold = {"a": "h1-new", "b": "h2", "c": "h3"}
    indexed = {"a": ("h1", MODEL), "b": ("h2", MODEL), "z": ("h9", MODEL)}

    plan = plan_sync(gold, indexed, MODEL)

    assert plan == SyncPlan(to_delete=["z"], to_embed=["a", "c"], unchanged=1)


def test_a_different_model_forces_reembedding_even_with_identical_text():
    """Deux modèles produisent des vecteurs incomparables : un document indexé par un
    autre modèle doit être recalculé, même si son texte n'a pas changé."""
    plan = plan_sync({"a": "h1"}, {"a": ("h1", "autre@b+onnx:2")}, MODEL)

    assert plan.to_embed == ["a"]


def test_empty_gold_is_always_refused_even_when_forced():
    plan = plan_sync({}, {"a": ("h1", MODEL)}, MODEL)

    with pytest.raises(MassDeletionError, match="vide"):
        check_deletion_guard(plan, gold_count=0, indexed_count=1, max_ratio=0.05, force=True)


def test_deleting_more_than_the_ratio_is_refused():
    indexed = {f"d{i}": ("h", MODEL) for i in range(100)}
    gold = {f"d{i}": "h" for i in range(94)}
    plan = plan_sync(gold, indexed, MODEL)

    with pytest.raises(MassDeletionError, match="6 suppressions"):
        check_deletion_guard(plan, gold_count=94, indexed_count=100, max_ratio=0.05)


def test_deleting_up_to_the_ratio_is_allowed():
    indexed = {f"d{i}": ("h", MODEL) for i in range(100)}
    gold = {f"d{i}": "h" for i in range(95)}
    plan = plan_sync(gold, indexed, MODEL)

    check_deletion_guard(plan, gold_count=95, indexed_count=100, max_ratio=0.05)


def test_force_allows_a_legitimate_mass_deletion():
    indexed = {f"d{i}": ("h", MODEL) for i in range(100)}
    plan = plan_sync({"d0": "h"}, indexed, MODEL)

    check_deletion_guard(plan, gold_count=1, indexed_count=100, max_ratio=0.05, force=True)
