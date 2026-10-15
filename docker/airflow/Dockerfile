# Image Airflow + dépendances du projet (pipeline et indexation RAG), Airflow épinglé pour que pip n'y touche pas.
FROM apache/airflow:3.3.1-python3.12

COPY requirements.txt /tmp/requirements.txt
COPY RAG/requirements.txt /tmp/rag-requirements.txt
RUN pip install --no-cache-dir "apache-airflow==3.3.1" -r /tmp/requirements.txt -r /tmp/rag-requirements.txt
