# Backend Genomica — Litestar + Piccolo + PostgreSQL

Backend for frontend de l'application Genomica, construit sur le starter imposé
[`Dakar2024/api-starter-Litestar`](https://github.com/Dakar2024/api-starter-Litestar).
Modèle de données et logique métier : [`MODELISATION_BACKEND.md`](MODELISATION_BACKEND.md).

**Écarts avec le starter** : uv au lieu de `requirements.txt` ; PyJWT au lieu de `python-jose`
(GHSA-3qf3-8w2g-rqmx, sans correctif) ; routes métier sous `/api` ; erreurs `{"error", "message"}` ;
JSON en camelCase (`core/schemas.py`) ; compteurs de débit dans Redis ; plus de MinIO public ni d'avatar.

---

## Stack

| Couche | Technologie |
|---|---|
| Framework | [Litestar](https://litestar.dev) — async ASGI, OpenAPI auto-généré |
| ORM & Migrations | [Piccolo](https://piccolo-orm.com) — async, migrations intégrées |
| Base de données | PostgreSQL 16 |
| Auth | JWT PyJWT (HTTP-only cookie) + Argon2 (hachage mot de passe) |
| Validation | Pydantic v2 + pydantic-settings |
| Email | aiosmtplib + Jinja2 (templates HTML), Resend en SMTP |
| Tests | Pytest + Litestar TestClient |
| Task queue | [Huey](https://huey.readthedocs.io) + Redis — tâches async et cron jobs |
| Serveur prod | Uvicorn (`--workers 2`) |
| Outillage | uv (`uv.lock`), ruff |

---

## Structure

```
api-starter/
│
├── app.py                  # Entrypoint — instancie l'app Litestar
├── pyproject.toml · uv.lock
├── Dockerfile
├── compose.yml             # API + worker + PostgreSQL + Redis
├── Makefile                # Commandes dev
│
├── core/                   # Utilitaires partagés entre toutes les features
│   ├── settings.py         # Variables d'environnement (pydantic-settings)
│   ├── database.py         # Connexion PostgreSQL + registre des migrations Piccolo
│   ├── exceptions.py       # Hiérarchie d'erreurs + handlers HTTP
│   ├── guards.py           # session_guard, active_user_guard, onboarding_guard, admin_guard
│   ├── security.py         # contrôle d'Origin (CSRF), IP du client, limites par e-mail/IP
│   ├── redis.py            # client Redis partagé
│   ├── mail.py             # send_email() — transport SMTP générique
│   ├── schemas.py          # CamelModel, base des schémas (camelCase sur le réseau)
│   └── worker.py           # instance Huey
│
├── features/               # Un dossier par domaine métier
│   └── auth/               # Feature authentification (incluse par défaut)
│       ├── controller.py   # Routes HTTP (/auth/*, /users/*)
│       ├── service.py      # Logique métier (stubs à implémenter)
│       ├── schemas.py      # Pydantic request/response models
│       ├── tables.py       # Tables Piccolo (User, PasswordResetToken)
│       ├── helpers.py      # JWT, hachage, user_to_response, email helpers
│       ├── exceptions.py   # Exceptions spécifiques auth
│       ├── piccolo_app.py  # Déclaration des tables pour les migrations
│       ├── templates/      # Templates HTML des emails (Jinja2)
│       │   └── reset_password.html
│       └── test_*.py       # Tests Pytest, à côté du code testé
│
└── scripts/
    └── new_feature.py      # Générateur de feature (voir Makefile)
```

---

## Démarrage rapide

### Prérequis
- Docker + Docker Compose, avec la pile données/RAG du dépôt démarrée : `compose.yml` rejoint son
  réseau externe `genomique_rag-api-ingress`.
- [uv](https://docs.astral.sh/uv/) pour le développement local (Python 3.13 installé par uv).

### 1. Configurer

```bash
cp .env.example .env   # remplir SECRET_KEY, POSTGRES_PASSWORD, ADMIN_*, MAIL_*
```

### 2. Lancer avec Docker

```bash
make up
```

- **API** → http://localhost:8100 (8000 est pris par Portainer sur cette machine)
- **Docs** → http://localhost:8100/docs
- **PostgreSQL** → 127.0.0.1:5433

Les migrations sont appliquées au démarrage ; le code est monté et rechargé à chaud.

### 3. Tests et lint

```bash
make test               # tests unitaires, sans base ni Redis
make test-integration   # PostgreSQL et Redis jetables (compose.test.yml), puis tests marqués integration
make lint               # uv run ruff check .
```

> Sous WSL, ne pas créer le `.venv` dans la copie `C:` si uv est aussi utilisé depuis Windows :
> les binaires d'un environnement ne servent pas à l'autre.

---

## Variables d'environnement

Copier `.env.example` → `.env` et remplir les champs. Les champs sans valeur par défaut sont **obligatoires** — l'API refusera de démarrer si l'un d'eux est manquant.

| Variable | Obligatoire | Description |
|---|---|---|
| `POSTGRES_USER` | Oui | Utilisateur PostgreSQL |
| `POSTGRES_PASSWORD` | Oui | Mot de passe PostgreSQL |
| `POSTGRES_DB` | Oui | Nom de la base de données |
| `SECRET_KEY` | Oui | Clé de signature JWT |
| `ADMIN_EMAIL` | Oui | Email du compte admin créé au démarrage |
| `ADMIN_PASSWORD` | Oui | Mot de passe du compte admin |
| `APP_NAME` | Non | Nom affiché dans les emails et l'OpenAPI |
| `ALLOWED_ORIGINS` | Non | Liste JSON des origines CORS autorisées |

---

## Ajouter une feature

```bash
make feature name=clients
```

Génère automatiquement dans `features/clients/` :

```
controller.py   service.py   schemas.py   tables.py
helpers.py      exceptions.py   piccolo_app.py
test_clients.py   templates/   migrations/
```

Ensuite :

1. **Implémenter** `features/clients/service.py`
2. **Enregistrer la table** dans `core/database.py` :
   ```python
   APP_REGISTRY = AppRegistry(apps=[
       "features.auth.piccolo_app",
       "features.clients.piccolo_app",  # ← ajouter
   ])
   ```
3. **Enregistrer le controller** dans `app.py` :
   ```python
   from features.clients.controller import ClientsController

   app = Litestar(
       route_handlers=[..., ClientsController],
   )
   ```
4. **Créer la migration** :
   ```bash
   make migration app=clients
   ```

---

## Commandes Makefile

| Commande | Description |
|---|---|
| `make up` | Lance tous les services Docker |
| `make down` | Arrête les services Docker |
| `make logs` | Affiche les logs de l'API |
| `make dev` | Serveur local avec hot-reload |
| `make install` | Installe les dépendances (`uv sync`) |
| `make migrate` | Applique toutes les migrations |
| `make migration app=xxx` | Génère une migration pour la feature `xxx` |
| `make feature name=xxx` | Génère le squelette d'une nouvelle feature |
| `make worker` | Lance le worker Huey en local |
| `make test` | Lance tous les tests Pytest |
| `make lint` | Lance ruff |

---

## Comptes — routes

Cycle de vie et règles : `MODELISATION_BACKEND.md` § 4.1. Toutes les routes sont sous `/api`.
Corps JSON en camelCase ; erreurs au format `{"error": <code>, "message": <texte>}`.

| Méthode | Route | Garde | Description |
|---|---|---|---|
| `POST` | `/auth/register` | public, limité | demande d'accès (réponse neutre, 202) |
| `POST` | `/auth/verify-email` | public, limité | consomme le lien, passe à `onboarding` |
| `POST` | `/auth/resend-verification` | public, limité | nouveau lien (réponse neutre) |
| `POST` | `/auth/login` | public, limité | cookie de session ; `remember` → cookie de 30 jours |
| `DELETE` | `/auth/logout` | — | supprime le cookie |
| `GET` | `/auth/me` | `active` ou `onboarding` | profil, dont `status` |
| `PATCH` | `/auth/me` | `active` | nom, fonction, établissement |
| `PATCH` | `/auth/me/password` | `active` | ferme les autres sessions |
| `POST` | `/auth/forgot-password` · `/auth/reset-password` | public, limité | lien valable 60 min |
| `PUT` | `/me/onboarding` | `onboarding` | profil complété → examen (ou actif en `open_domains`) |
| `DELETE` | `/me` | `active` ou `onboarding` | effacement du compte (mot de passe requis) |
| `GET` | `/admin/requests` | admin | profils en attente d'examen |
| `POST` | `/admin/requests/{id}/approve` · `/reject` | admin | décision, e-mail et audit |

Codes d'erreur propres aux comptes : `invalid_credentials`, `account_pending_email`,
`account_pending_review`, `account_rejected`, `account_suspended`, `email_not_professional`,
`registration_closed`, `invalid_token`, `invalid_password`, `invalid_transition`, `last_admin`.

---

## Protéger une route

```python
from core.guards import active_user_guard

class MyController(Controller):
    guards = [active_user_guard]  # toutes les routes du controller
```

ou sur une route spécifique :

```python
@get("/secret", guards=[admin_guard])
async def secret(self) -> dict:
    ...
```

---

## Tâches en arrière-plan (Huey)

Les tâches sont définies dans `features/<feature>/tasks.py` et exécutées par le worker Huey.
Chaque module de tâches doit être importé dans `core/tasks.py` : c'est ce que charge le worker.

**Tâche ponctuelle** — déclenché depuis un controller ou un service :

```python
# features/auth/tasks.py
@huey.task()
def send_welcome_task(to_email: str, name: str) -> None:
    asyncio.run(send_welcome_email(to_email, name))

# Appel depuis le service (non bloquant)
send_welcome_task(user.email, user.full_name)
```

**Cron job** — s'exécute automatiquement selon le planning :

```python
@huey.periodic_task(crontab(minute="0", hour="3"))  # tous les jours à 3h
def cleanup_expired_tokens() -> None:
    ...
```

**Lancer le worker en local :**

```bash
make worker
```

En production le worker tourne comme service Docker séparé (`worker` dans `compose.yml`).

---

## Envoyer un email

Ajouter un template HTML dans `features/ma_feature/templates/`, puis dans `helpers.py` :

```python
async def send_welcome_email(to_email: str, name: str) -> None:
    await send_email(
        to=to_email,
        subject=f"Bienvenue — {settings.APP_NAME}",
        text=f"Bonjour {name}",
        html=_render("welcome.html", name=name),
    )
```
