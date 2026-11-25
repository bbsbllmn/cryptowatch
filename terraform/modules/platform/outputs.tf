output "lake_bucket" { value = google_storage_bucket.lake.name }
output "composer_dag_gcs_prefix" { value = google_composer_environment.airflow.config[0].dag_gcs_prefix }
