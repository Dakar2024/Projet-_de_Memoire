#!/usr/bin/env python3
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/new_feature.py <feature_name>")
        sys.exit(1)

    name = sys.argv[1].lower()
    cap  = name.capitalize()
    base = Path("features") / name

    if base.exists():
        print(f"La feature '{name}' existe déjà.")
        sys.exit(1)

    # Dossiers
    (base / "migrations").mkdir(parents=True)
    (base / "templates").mkdir()

    files = {
        "__init__.py": "",
        "migrations/__init__.py": "",

        "helpers.py": f"# Fonctions utilitaires pour la feature {name}\n",

        "schemas.py": (
            "from pydantic import BaseModel\n\n\n"
            "# class CreateRequest(BaseModel):\n"
            "#     ...\n\n"
            "# class UpdateRequest(BaseModel):\n"
            "#     ...\n\n"
            f"# class {cap}Response(BaseModel):\n"
            "#     ...\n"
        ),

        "tables.py": (
            "from piccolo.columns import Varchar, Timestamptz, UUID\n"
            "from piccolo.table import Table\n\n\n"
            f"class {cap}(Table, tablename=\"{name}s\"):\n"
            "    id         = UUID(primary_key=True)\n"
            "    created_at = Timestamptz(auto_now_add=True)\n"
        ),

        "exceptions.py": (
            "from core.exceptions import NotFoundError, AlreadyExistsError\n\n\n"
            f"class {cap}NotFoundError(NotFoundError):\n"
            "    def __init__(self, identifier: str) -> None:\n"
            f"        super().__init__(f\"{cap} '{{identifier}}' introuvable\")\n"
        ),

        "service.py": (
            f"class {cap}Service:\n"
            "    pass\n"
        ),

        "controller.py": (
            "from litestar import Controller, get, post, patch, delete\n"
            "from litestar.di import Provide\n\n"
            "from core.guards import active_user_guard\n"
            f"from features.{name}.service import {cap}Service\n\n\n"
            f"def provide_{name}_service() -> {cap}Service:\n"
            f"    return {cap}Service()\n\n\n"
            f"class {cap}Controller(Controller):\n"
            f"    path         = \"/{name}\"\n"
            f"    tags         = [\"{cap}\"]\n"
            "    guards       = [active_user_guard]\n"
            f"    dependencies = {{\"service\": Provide(provide_{name}_service, sync_to_thread=False)}}\n\n"
            "    # @get(\"/\")\n"
            f"    # async def list(self, service: {cap}Service):\n"
            "    #     raise NotImplementedError\n\n"
            "    # @post(\"/\")\n"
            f"    # async def create(self, service: {cap}Service):\n"
            "    #     raise NotImplementedError\n"
        ),

        "piccolo_app.py": (
            "from piccolo.conf.apps import AppConfig\n"
            f"from features.{name}.tables import {cap}\n\n\n"
            "APP_CONFIG = AppConfig(\n"
            f"    app_name=\"{name}\",\n"
            f"    migrations_folder_path=\"features/{name}/migrations\",\n"
            f"    table_classes=[{cap}],\n"
            ")\n"
        ),

        "tasks.py": (
            "from core.worker import huey\n\n\n"
            "# Tâche en arrière-plan\n"
            "# @huey.task()\n"
            f"# def {name}_task(param: str) -> None:\n"
            "#     ...\n\n\n"
            "# Tâche planifiée (cron)\n"
            "# @huey.periodic_task(crontab(minute='0', hour='9'))  # tous les jours à 9h\n"
            f"# def {name}_daily_job() -> None:\n"
            "#     ...\n"
        ),

        f"test_{name}.py": (
            "import pytest\n"
            "from litestar.testing import TestClient\n\n"
            "from app import app\n\n\n"
            "@pytest.fixture\n"
            "def client():\n"
            "    with TestClient(app=app) as c:\n"
            "        yield c\n\n\n"
            f"# def test_list_{name}s(client: TestClient):\n"
            f"#     response = client.get(\"/{name}/\")\n"
            "#     assert response.status_code == 200\n"
        ),
    }

    for filename, content in files.items():
        path = base / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    print(f"\nFeature '{name}' créée dans features/{name}/\n")
    print("Prochaines étapes :")
    print(f"  1. Implémenter features/{name}/service.py")
    print(f"  2. Enregistrer dans core/database.py  ->  'features.{name}.piccolo_app'")
    print(f"  3. Enregistrer dans app.py            ->  {cap}Controller")
    print(f"  4. make migration app={name}")
    print(f"  5. Si la feature a des tâches Huey : importer features.{name}.tasks dans core/tasks.py")

if __name__ == "__main__":
    main()
