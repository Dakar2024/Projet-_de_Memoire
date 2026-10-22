# Genomica — frontend

Interface web de Genomica : page d'accueil publique, connexion et demande d'accès, puis espace connecté
(assistant, explorateur, administration). Construite sur le starter `react-app-starter-with-tanstack` :
**TanStack Start** (SSR), **Bun**, **Tailwind CSS v4**, **shadcn/ui**, **TanStack Query**, **Lingui** (FR/EN).

Design de référence : canvas « Genomica — Proposition de design ». Contrat d'API :
`apps/backend/MODELISATION_BACKEND.md`.

## Démarrer (Windows, PowerShell)

```powershell
cd apps\frontend
bun install
Copy-Item .env.example .env
bun dev            # http://localhost:3000/fr
```

`node_modules` dépend du système : installer et lancer depuis le même environnement (ici Windows).

Tant que le backend n'existe pas, `VITE_USE_MOCKS=true` active un faux backend en mémoire :

| Compte | E-mail | Mot de passe |
|---|---|---|
| Utilisateur | `demo@genomica.local` | `genomica-demo-2026` |
| Administrateur | `admin@genomica.local` | `genomica-demo-2026` |

Une demande d'accès crée un compte « en attente de vérification de l'e-mail » ; la connexion à ce compte
mène à l'écran d'attente. Le faux backend se vide à chaque redémarrage.

## Commandes

| Commande | Rôle |
|---|---|
| `bun dev` | serveur de développement |
| `bun run build` puis `bun run server.ts` | build et serveur de production (Bun) |
| `bun run test` | tests Vitest (logique : schémas, robustesse du mot de passe, faux backend) |
| `bun x tsc -p tsconfig.json --noEmit` | vérification des types |
| `bun run extract` puis `bun run compile` | mise à jour des catalogues de traduction après ajout de textes |

## Architecture

```
src/
  app/                      routes (fichier = URL), toutes préfixées par la langue
    $lang/route.tsx         valide la langue
    $lang/index.tsx         accueil (données chargées pendant le SSR)
    $lang/_auth.tsx         gabarit écran scindé ; redirige vers l'assistant si déjà connecté
    $lang/_auth/*           sign-in, sign-up, pending, forgot-password
    $lang/_app.tsx          espace connecté ; garde d'accès dans beforeLoad
  features/<domaine>/       composants, hooks, server functions et schémas d'un domaine
  shared/api/               contrat d'API (types), erreurs, accès serveur au backend
  shared/mocks/             faux backend (chiffres réels du gold au 2026-10-22)
  shared/components/        logo, bascule de thème, composants shadcn (ui/)
  styles.css                jetons de design : thème clair/sombre, 4 couleurs d'accent, couleurs cliniques
```

Choix structurants :

- **Le navigateur ne parle qu'au backend Genomica**, jamais à l'API RAG (dont la clé reste côté serveur).
- **Session et garde d'accès passent par des server functions** : la garde s'exécute aussi pendant le
  SSR, et seul le serveur peut lire le cookie de session `httpOnly`. En mode réel, elles relaient
  simplement la requête vers le backend (`API_INTERNAL_URL`) avec le cookie du navigateur.
- **Appels du navigateur en même origine** (`/api/*`), relayés par le proxy Vite en développement.
- **Couleur d'accent** dans un cookie lu côté serveur : la page s'affiche directement dans la bonne
  couleur. Le thème clair/sombre suit le système par défaut (`next-themes`).
- **Couleurs des classifications cliniques** (`--sig-*`) indépendantes de l'accent et validées pour les
  daltonismes ; ne pas les modifier sans revalider.
- **Polices auto-hébergées** (`@fontsource-variable/geist`) : aucun appel à Google Fonts.

## Traductions

Le français est la langue source. Les 176 messages anglais restent à traduire dans
`src/locales/en/messages.po` ; en attendant, la version anglaise affiche le texte français.
