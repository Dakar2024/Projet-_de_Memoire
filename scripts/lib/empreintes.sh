# Empreintes partagées par les vérifications de restauration et scripts/comparer_piles.sh.
# À sourcer depuis un script lancé à la racine du dépôt : . scripts/lib/empreintes.sh
# shellcheck shell=bash disable=SC2034  # NOMS et SQL sont lus par comparer_requetes et les appelants

# Base Airflow : seul l'historique figé au moment du dump se compare, runs et tâches terminés avant.
empreintes_airflow() {  # date de création du dump (« ; Archive created at » de pg_restore --list)
  NOMS=(
    "version du schéma Airflow"
    "runs terminés avant le dump"
    "tâches terminées avant le dump"
  )
  SQL=(
    "SELECT version_num FROM alembic_version"
    "SELECT count(*) || ' runs, empreinte ' || coalesce(md5(string_agg(dag_id || '/' || run_id || '=' || state, ',' ORDER BY dag_id, run_id)), '-') FROM dag_run WHERE end_date < '$1'"
    "SELECT count(*) || ' tâches, empreinte ' || coalesce(md5(string_agg(dag_id || '/' || run_id || '/' || task_id || '/' || map_index || '/' || try_number || '=' || coalesce(state, ''), ',' ORDER BY dag_id, run_id, task_id, map_index)), '-') FROM task_instance WHERE end_date < '$1'"
  )
}

# Base vectorielle : contenu, vecteurs, index, droits et un vrai calcul de voisinage.
empreintes_rag() {
  NOMS=(
    "documents et modèles d'embedding"
    "empreinte des identifiants (doc_id, chunk_id)"
    "empreinte des vecteurs"
    "index"
    "droits de rag_reader et rag_indexer"
    "10 plus proches voisins (recherche exacte)"
  )
  SQL=(
    "SELECT count(*) || ' documents, ' || count(DISTINCT embedding_model) || ' modèle(s) : ' || string_agg(DISTINCT embedding_model, ', ') FROM rag_documents"
    "SELECT md5(string_agg(doc_id || ':' || chunk_id, ',' ORDER BY doc_id)) FROM rag_documents"
    "SELECT md5(string_agg(md5(embedding::text), '' ORDER BY doc_id)) FROM rag_documents"
    "SELECT string_agg(indexname, ', ' ORDER BY indexname) FROM pg_indexes WHERE tablename = 'rag_documents'"
    "SELECT 'lecteur lit=' || has_table_privilege('rag_reader', 'rag_documents', 'SELECT') || ' écrit=' || has_table_privilege('rag_reader', 'rag_documents', 'INSERT') || ' ; indexeur écrit=' || has_table_privilege('rag_indexer', 'rag_documents', 'INSERT')"
    "SET enable_indexscan = off; SELECT string_agg(doc_id, ',') FROM (SELECT doc_id FROM rag_documents ORDER BY embedding <=> (SELECT embedding FROM rag_documents ORDER BY doc_id LIMIT 1), doc_id LIMIT 10) t"
  )
}

# Exécute chaque requête de SQL à l'identique dans deux conteneurs ; incrémente `ecarts` à chaque différence.
comparer_requetes() {  # utilisateur base conteneur_reference conteneur_compare libelle_reference libelle_compare
  local i attendu obtenu
  for i in "${!SQL[@]}"; do
    attendu="$(docker exec "$3" psql -U "$1" -d "$2" -At -c "${SQL[$i]}" | tail -n 1)"
    obtenu="$(docker exec "$4" psql -U "$1" -d "$2" -At -c "${SQL[$i]}" | tail -n 1)"
    if [ "${attendu}" = "${obtenu}" ]; then
      echo "   OK     ${NOMS[$i]} : ${obtenu:0:90}"
    else
      echo "   ÉCART  ${NOMS[$i]}"
      echo "          $5 : ${attendu:0:90}"
      echo "          $6 : ${obtenu:0:90}"
      ecarts=$((ecarts + 1))
    fi
  done
}

# Une ligne « sha256  chemin » par fichier des quatre buckets, triée : comparable octet pour octet.
empreintes_fichiers() {  # dossier contenant raw/ bronze/ silver/ gold/
  (cd "$1" && find raw bronze silver gold -type f -print0 | sort -z | xargs -0 sha256sum)
}
