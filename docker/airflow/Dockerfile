FROM apache/airflow:3.3.1-python3.12

# Les tâches TaskFlow et le dag-processor exécutent le code du projet dans
# l'interpréteur d'Airflow : les dépendances doivent y être installées. Épingler
# apache-airflow dans la même commande empêche pip de modifier Airflow.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir "apache-airflow==3.3.1" -r /tmp/requirements.txt
