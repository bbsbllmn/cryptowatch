locals {
  p      = var.project_id
  prefix = "crypto-${var.env}"
  labels = { app = "cryptowatch", env = var.env }
  ops_tables = {
    notification_ledger = {
      partition = "attempted_at"
      schema = [
        { name = "ds", type = "DATE", mode = "REQUIRED" }, { name = "channel", type = "STRING", mode = "REQUIRED" },
        { name = "status", type = "STRING", mode = "REQUIRED" }, { name = "alert_count", type = "INT64", mode = "NULLABLE" },
        { name = "detail", type = "STRING", mode = "NULLABLE" }, { name = "attempted_at", type = "TIMESTAMP", mode = "REQUIRED" },
      ]
    }
    pipeline_runs = {
      partition = "finished_at"
      schema = [
        { name = "ds", type = "DATE", mode = "REQUIRED" }, { name = "run_id", type = "STRING", mode = "REQUIRED" },
        { name = "status", type = "STRING", mode = "REQUIRED" }, { name = "failed_tasks", type = "STRING", mode = "REPEATED" },
        { name = "finished_at", type = "TIMESTAMP", mode = "REQUIRED" },
      ]
    }
  }
}

resource "google_project_service" "apis" {
  for_each           = toset(["bigquery.googleapis.com", "storage.googleapis.com", "composer.googleapis.com", "secretmanager.googleapis.com", "iam.googleapis.com"])
  project            = local.p
  service            = each.key
  disable_on_destroy = false
}

resource "google_storage_bucket" "lake" {
  name                        = "${local.prefix}-lake-${local.p}"
  project                     = local.p
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels
  versioning { enabled = true } # the raw snapshot is the only copy of a day the API cannot re-serve
  depends_on = [google_project_service.apis]
}

resource "google_bigquery_dataset" "ds" {
  for_each                   = toset(["raw", "staging", "gold", "ops"])
  project                    = local.p
  dataset_id                 = "crypto_${each.key}"
  location                   = var.bq_location
  labels                     = local.labels
  delete_contents_on_destroy = var.env != "prod"
  depends_on                 = [google_project_service.apis]
}

resource "google_bigquery_table" "ops" {
  for_each            = local.ops_tables
  project             = local.p
  dataset_id          = google_bigquery_dataset.ds["ops"].dataset_id
  table_id            = each.key
  deletion_protection = var.env == "prod"
  schema              = jsonencode(each.value.schema)
  time_partitioning {
    type  = "DAY"
    field = each.value.partition
  }
}

resource "google_service_account" "composer" {
  project      = local.p
  account_id   = "${local.prefix}-composer"
  display_name = "Composer workers for cryptowatch"
}

resource "google_project_iam_member" "composer_roles" {
  for_each = toset(["roles/composer.worker", "roles/bigquery.jobUser"])
  project  = local.p
  role     = each.key
  member   = "serviceAccount:${google_service_account.composer.email}"
}
resource "google_storage_bucket_iam_member" "lake_rw" {
  bucket = google_storage_bucket.lake.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.composer.email}"
}
resource "google_bigquery_dataset_iam_member" "editor" {
  for_each   = google_bigquery_dataset.ds
  project    = local.p
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.composer.email}"
}

# Secret VALUES are set out-of-band (never in Terraform state): coingecko-demo-key, slack-webhook-url,
# smtp-config (JSON: host, port, user, password, from, to[]), anthropic-api-key).
resource "google_secret_manager_secret" "s" {
  for_each  = toset(["coingecko-demo-key", "slack-webhook-url", "smtp-config", "anthropic-api-key"])
  project   = local.p
  secret_id = each.key
  replication {
    auto {}
  }
}
resource "google_secret_manager_secret_iam_member" "read" {
  for_each  = google_secret_manager_secret.s
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.composer.email}"
}

resource "google_composer_environment" "airflow" {
  name    = "${local.prefix}-airflow"
  project = local.p
  region  = var.region
  labels  = local.labels
  config {
    software_config {
      image_version = var.composer_image_version
      pypi_packages = { "dbt-bigquery" = ">=1.10", "anthropic" = ">=0.40", "google-cloud-secret-manager" = "", "requests" = "" }
      env_variables = {
        CW_PROJECT     = local.p
        CW_REGION      = var.region
        CW_BQ_LOCATION = var.bq_location
        CW_LAKE_BUCKET = google_storage_bucket.lake.name
        CW_DBT_TARGET  = "prod"
        CW_CHANNELS    = var.channels
      }
    }
    node_config { service_account = google_service_account.composer.email }
  }
  depends_on = [google_project_iam_member.composer_roles]
}
