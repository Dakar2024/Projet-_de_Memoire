# Choix du modèle d'embedding — BioBERT ou NeuML PubMedBERT

**Date de la mesure :** 4 octobre 2026
**Données :** `gold/rag/documents`, archive ClinVar de septembre 2026, 96 910 documents
**Spec :** `docs/superpowers/specs/2026-10-01-sous-projet-e1-indexation-rag-design.md`, §6
**Décision :** **NeuML PubMedBERT est retenu**, par application de la règle fixée avant la mesure.

---

## 1. Question posée

Pour la partie sémantique de la recherche, `NeuML/pubmedbert-base-embeddings` retrouve-t-il
les bons documents mieux que BioBERT brut (`dmis-lab/biobert-base-cased-v1.2`), annoncé dans le
mémoire, **sur nos propres données** ?

La question se posait pour une raison précise. La fiche de BioBERT le classe en `fill-mask` : il
est entraîné à prédire un mot masqué, pas à rapprocher deux textes de même sens. On peut en
extraire un vecteur par moyenne des tokens, mais rien ne garantit que ce vecteur serve à la
recherche. NeuML, construit sur PubMedBERT, est au contraire entraîné par apprentissage
contrastif sur des paires de textes PubMed, précisément pour cet usage.

## 2. Candidats

| Modèle | Révision épinglée | Retenu pour la mesure | Raison |
|---|---|---|---|
| `dmis-lab/biobert-base-cased-v1.2` | `67c9c25b4698` | oui | annoncé par le mémoire |
| `NeuML/pubmedbert-base-embeddings` | `b79526d6ef36` | oui | entraîné pour la similarité, Apache 2.0, 768 dimensions, 512 tokens |
| `pritamdeka/S-PubMedBert-MS-MARCO` | — | non | fenêtre de 350 tokens et licence non commerciale (CC-BY-NC) |
| `ncbi/MedCPT` | — | non | requête limitée à 64 tokens ; encodeur de documents entraîné sur des articles, pas sur des fiches de variants |

Les deux modèles mesurés ont été exportés en ONNX par le même outil (`docker/embeddings/`),
avec des dépendances verrouillées par empreinte. Empreintes des exports :

- BioBERT : `dmis-lab/biobert-base-cased-v1.2@67c9c25b4698+onnx:e70165ca2c88cc4a`
- NeuML : `NeuML/pubmedbert-base-embeddings@b79526d6ef36+onnx:2ab209f97e0a83ca`

L'export de NeuML a donné une empreinte identique à celle d'un essai indépendant du 2 octobre :
l'export est reproductible.

## 3. Protocole

- **Corpus complet.** Les 96 910 documents sont vectorisés par chaque modèle, sans
  échantillonnage. Le calcul s'est fait sur GPU. C'est légitime : une mesure du 1ᵉʳ octobre a
  montré que GPU et CPU donnent pour un même texte un cosinus d'au moins 0,99897, et les mêmes
  dix plus proches voisins dans 99,9 % des cas.
- **Recherche exacte.** Chaque question est comparée à tous les documents (produit scalaire
  de vecteurs normalisés, donc cosinus). On mesure ainsi le modèle, pas l'approximation d'un
  index.
- **59 questions en anglais, sans identifiant.** Aucun `rs` ni HGVS : ces questions-là
  relèvent de la correspondance exacte, pas du modèle.

  | Famille | n | Question type | Pertinent | Métrique |
  |---|---|---|---|---|
  | A | 18 | rôle d'un gène, une par gène | la fiche `gene:<SYMBOLE>` | rang réciproque |
  | B | 21 | maladie dans un gène, recherche filtrée sur ce gène | variants du gène associés à la maladie | précision sur les 10 premiers |
  | C | 20 | signification et maladie, tout le panel | variants de cette signification associés à la maladie | précision sur les 10 premiers |

- **Pertinence calculée sur les métadonnées.** Elle repose sur le gène, la signification
  clinique et la table Silver `clinvar_variant_disease`. Elle n'est jamais jugée à la main ni
  par un LLM : n'importe qui peut la recalculer.
- **Questions reformulées.** Les questions ne recopient pas le nom des maladies : elles disent
  par exemple « signet ring cell stomach cancer » pour *Hereditary diffuse gastric
  adenocarcinoma*. On mesure ainsi le sens, pas le recouvrement de mots. Chaque question B ou C
  a au moins 50 documents pertinents (le minimum exigé était 10).
- **Questions validées par l'utilisateur le 4 octobre 2026**, avant toute mesure.
- **Règle de décision fixée avant la mesure.** On compare les deux modèles question par
  question, et on calcule un intervalle de confiance à 95 % de l'écart moyen par bootstrap
  (10 000 rééchantillonnages, graine fixe `20261001`). NeuML n'est retenu que si l'écart est
  positif **et** que l'intervalle exclut zéro. Sinon BioBERT est conservé.
- **Garde-fous contre une mesure fausse mais bien présentée.** Chaque vectorisation écrit un
  manifeste : liste des documents, empreinte des contenus, empreinte du fichier de questions,
  empreinte du modèle exporté. L'évaluation refuse de conclure dans quatre cas :
  - les manifestes ne concordent pas entre eux ou avec les données actuelles ;
  - les deux empreintes de modèle sont identiques ;
  - les labels ne sont pas exactement BioBERT et NeuML ;
  - les vecteurs des deux modèles sont quasi identiques, signe que le même modèle aurait servi
    deux fois.

  L'évaluation est allée à son terme : aucun de ces cas ne s'est produit.

## 4. Résultats

Sortie de `evaluer`, recopiée sans modification :

| Famille | n | BioBERT | NeuML |
|---|---|---|---|
| A | 18 | 0.369 | 0.853 |
| B | 21 | 0.500 | 0.862 |
| C | 20 | 0.055 | 0.305 |

**Écart moyen NeuML − BioBERT : +0,361, IC 95 % [+0,257 ; +0,469].**

Par famille, à titre indicatif seulement :

| Famille | Écart | IC 95 % |
|---|---|---|
| A | +0,484 | [+0,265 ; +0,695] |
| B | +0,362 | [+0,186 ; +0,548] |
| C | +0,250 | [+0,120 ; +0,395] |

Ce que disent ces chiffres :

- **Famille A.** NeuML place la fiche du bon gène presque toujours en tête (rang réciproque
  moyen 0,853). BioBERT la place en moyenne vers le troisième rang (0,369).
- **Famille B.** Même à l'intérieur d'un seul gène, NeuML trouve des variants de la bonne
  maladie dans 86 % des dix premiers résultats, contre 50 % pour BioBERT.
- **Famille C.** C'est la plus difficile, et les scores y sont bas pour les deux modèles.
  BioBERT n'y trouve presque rien (5,5 %), NeuML trouve 30,5 % de documents pertinents. Ce
  résultat confirme la contrainte n° 1 de la conception : la similarité vectorielle seule ne
  suffit pas à distinguer « pathogène » de « bénin » parmi des documents quasi jumeaux. La
  recherche de E2 devra filtrer sur la signification clinique.

## 5. Décision

L'écart est positif et l'intervalle de confiance exclut zéro. **La règle désigne NeuML
PubMedBERT.** Il devient le modèle d'embedding du RAG.

L'écart est cohérent dans les trois familles : chaque intervalle par famille exclut lui aussi
zéro. Ces intervalles ne servent pas à la décision, mais ils montrent que le résultat ne tient
pas à une seule famille de questions.

Ce choix s'écarte du BioBERT annoncé dans le mémoire. Il doit y être présenté comme un
résultat expérimental : BioBERT a été comparé à une alternative, sur les données du projet,
selon une règle fixée avant la mesure, et il a perdu nettement.

## 6. Limites

- **Questions écrites par nous.** Elles ont été validées par l'utilisateur, mais elles ne
  viennent pas de vrais utilisateurs. Leur formulation peut favoriser un modèle.
- **Questions uniquement en anglais.** Les utilisateurs écriront en français. E2 traduira la
  question en anglais avant la recherche : la qualité de cette reformulation n'est pas mesurée
  ici.
- **Une seule archive ClinVar** (septembre 2026).
- **Pertinence par sous-chaîne du nom de maladie.** Un variant associé à une maladie de nom
  voisin mais non listée compte comme non pertinent : la précision mesurée est donc un minimum.
- **Bootstrap groupé sur les trois familles,** comme la spec le fixait, alors que leurs
  métriques diffèrent (rang réciproque pour A, précision pour B et C). Les intervalles par
  famille, tous positifs, montrent que cela ne change pas la conclusion.
- **Seulement deux candidats.** NeuML n'est pas « le meilleur modèle possible ». Il est
  meilleur que BioBERT sur ces données.
- **Durée de vectorisation.** Il a fallu 29 minutes pour BioBERT et 22 minutes pour NeuML sur
  GPU, lecture des données comprise, au lieu des 7 minutes estimées d'après le débit brut du
  service. La différence vient du temps de lecture et de préparation des données, qui n'a pas
  été mesuré à part.
- **Avertissement de dépréciation Polars** (`is_in`) dans le calcul de la pertinence. Il est
  sans effet sur le résultat de Polars 1.44.1, mais il faudra le corriger avant une mise à jour
  de Polars.

## 7. Reproduire

```bash
cd ~/Documents/Projet-_de_Memoire
set -a; . ./.env; set +a
export AWS_ENDPOINT_URL=http://127.0.0.1:${MINIO_API_PORT} AWS_ACCESS_KEY_ID=$MINIO_AIRFLOW_USER \
       AWS_SECRET_ACCESS_KEY=$MINIO_AIRFLOW_PASSWORD AWS_REGION=us-east-1 LAKE_URI=s3:// PYTHONPATH=src

# Contrôle des questions
venv/bin/python -m RAG.experiments.comparaison_embeddings verifier-questions

# Vectorisation, un service temporaire par modèle (GPU)
for dir in biobert-base-cased-v1.2 pubmedbert-base-embeddings; do
  docker run -d --rm --name tei-comparaison --gpus all -p 127.0.0.1:18080:80 \
    -v "$PWD/data/models/$dir":/model:ro -e API_KEY="$RAG_EMBEDDINGS_API_KEY" \
    ghcr.io/huggingface/text-embeddings-inference:turing-1.9@sha256:f78d17832f00f59f7d52e4b3b8495264257de3c18b773357a00ee341b2af852d \
    --model-id /model --pooling mean
  until curl -sf http://127.0.0.1:18080/health >/dev/null; do sleep 2; done
  venv/bin/python -m RAG.experiments.comparaison_embeddings vectoriser --model-dir "data/models/$dir"
  docker stop tei-comparaison
done

# Évaluation et décision
venv/bin/python -m RAG.experiments.comparaison_embeddings evaluer
```

La même variable `$dir` sert à la fois au montage du conteneur et à `--model-dir`. Les deux ne
peuvent donc pas désigner deux modèles différents. Les scores par question sont dans
`data/experiments/scores.json`.
