terraform {
  required_version = ">= 1.6"
  required_providers { google = { source = "hashicorp/google", version = "~> 6.0" } }
  backend "gcs" {} # terraform init -backend-config="bucket=<state-bucket>" -backend-config="prefix=cryptowatch/dev"
}
variable "project_id" { type = string }
provider "google" {
  project = var.project_id
  region  = "europe-west1"
}
module "platform" {
  source     = "../../modules/platform"
  project_id = var.project_id
  env        = "dev"
}
output "composer_dag_gcs_prefix" { value = module.platform.composer_dag_gcs_prefix }
