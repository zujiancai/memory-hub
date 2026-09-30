# Memory Hub — Azure deployment (Phase 1)

Bicep templates that provision the Phase-1 Azure footprint into an existing
resource group.

## What gets provisioned

| Resource | Purpose |
| --- | --- |
| Linux App Service Plan + App Service (Python 3.11) | Hosts the Flask API and the built React SPA (`server/ui/dist`) |
| PostgreSQL Flexible Server (Burstable B1ms) | App database |
| Storage Account + `memoryhub-media` blob container | Media blobs (photos, videos, posters, avatars) |
| Key Vault | Holds JWT signing key, storage connection string, PostgreSQL URL, Google OAuth secrets |
| Application Insights + Log Analytics workspace | Telemetry |

The App Service has a **system-assigned managed identity** and is granted:

- **Storage Blob Data Contributor** on the storage account (so it can mint
  user-delegation SAS tokens for uploads/downloads)
- **Key Vault Secrets User** on the Key Vault (so it can resolve
  `@Microsoft.KeyVault(SecretUri=...)` references in app settings)

Secrets in `parameters.*.json` show `REPLACE_ME_WITH_PIPELINE_SECRET` — never
commit real values. Pipe them in through your deployment pipeline (Azure DevOps
variable groups or GitHub Actions secrets) via `--parameters` overrides.

## Prereqs

- Azure CLI ≥ 2.60
- An Azure subscription with Contributor + User Access Administrator
- Your AAD object ID (`az ad signed-in-user show --query id -o tsv`)

## Deploy

```powershell
# Create the resource group first
$rg = "memory-hub-dev"
az group create --name $rg --location eastus

# Fetch your object ID for the Key Vault RBAC assignment
$me = az ad signed-in-user show --query id -o tsv

# Deploy at resource-group scope
az deployment group create `
  --resource-group $rg `
  --template-file main.bicep `
  --parameters "@parameters.dev.json" `
  --parameters deployerObjectId=$me `
  --parameters postgresAdminPassword=$env:MH_PG_PASSWORD `
  --parameters jwtSigningKey=$env:MH_JWT_KEY `
  --parameters googleOAuthClientId=$env:MH_GOOGLE_CLIENT_ID `
  --parameters googleOAuthClientSecret=$env:MH_GOOGLE_CLIENT_SECRET
```

## Post-deploy

1. Package the app and deploy:

   ```powershell
   # From repo root
   cd server\ui; npm ci; npm run build; cd ..\..
   # Bundle the Python app (Oryx will pip install from requirements.txt on push)
   Compress-Archive -Path server\* -DestinationPath server-app.zip -Force
   az webapp deploy `
     --resource-group $rg `
     --name mh-dev-app `
     --src-path server-app.zip `
     --type zip
   ```

2. Run migrations against the provisioned Postgres:

   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg2://memoryhub_admin:...@mh-dev-pg.postgres.database.azure.com:5432/memoryhub?sslmode=require"
   pipenv run flask db upgrade
   ```

3. Enable HTTP/2 + custom domain / TLS binding as needed.

## Prod

Copy `parameters.prod.json`, adjust SKUs, and repeat with a `memory-hub-prod`
resource group. Prod uses `Standard_ZRS` storage and a `P1v3` plan by default.
