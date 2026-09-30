// Memory Hub — Phase 1 infrastructure
//
// Provisions a resource group scaffold for a single environment:
//   - Linux App Service Plan + App Service (Python 3.11) with system-assigned
//     managed identity
//   - PostgreSQL Flexible Server (Burstable B1ms) for the app DB
//   - Storage Account + blob container for media
//   - Key Vault holding the JWT signing key, Storage connection string,
//     PostgreSQL connection string, and Google OAuth secrets
//   - Application Insights + Log Analytics workspace
//
// RBAC: the App Service's managed identity is granted
//   - Storage Blob Data Contributor on the storage account
//   - Key Vault Secrets User on the Key Vault
//
// Secrets are surfaced to the App Service via `@Microsoft.KeyVault(...)`
// references in app settings — no plaintext in source.

targetScope = 'resourceGroup'

@description('Short name for the environment; used as suffix on resource names.')
param environmentName string

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Administrator login for the PostgreSQL server.')
param postgresAdminUser string = 'memoryhub_admin'

@secure()
@description('Administrator password for the PostgreSQL server.')
param postgresAdminPassword string

@secure()
@description('JWT signing key used by the Flask API to sign access tokens.')
param jwtSigningKey string

@description('Google OAuth 2.0 client ID for the web SPA.')
param googleOAuthClientId string

@secure()
@description('Google OAuth 2.0 client secret.')
param googleOAuthClientSecret string

@description('Object ID of the human/service principal that should have admin access to the Key Vault (e.g. your deploy identity).')
param deployerObjectId string

@description('SKU for the App Service Plan. Use P1v3 for prod, B2 for dev.')
param appServicePlanSku string = 'B2'

@description('Storage SKU. Standard_LRS is fine for dev.')
param storageSku string = 'Standard_LRS'

var namePrefix = 'mh-${environmentName}'
var storageAccountName = toLower(replace('mh${environmentName}sa${uniqueString(resourceGroup().id)}', '-', ''))
var mediaContainerName = 'memoryhub-media'
var keyVaultName = toLower('${namePrefix}-kv-${take(uniqueString(resourceGroup().id), 6)}')

// ---------- Storage Account ---------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: { name: storageSku }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource mediaContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: mediaContainerName
  properties: {
    publicAccess: 'None'
  }
}

// ---------- PostgreSQL Flexible Server ---------------------------------------
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: '${namePrefix}-pg'
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '15'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    authConfig: {
      passwordAuth: 'Enabled'
      activeDirectoryAuth: 'Disabled'
    }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgres
  name: 'memoryhub'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource postgresAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: postgres
  name: 'AllowAllAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ---------- Log Analytics + Application Insights -----------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-law'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-ai'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------- Key Vault ---------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enabledForTemplateDeployment: false
    enabledForDiskEncryption: false
    enabledForDeployment: false
    publicNetworkAccess: 'Enabled'
  }
}

var storageKeys = listKeys(storage.id, storage.apiVersion)
var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storageKeys.keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
var postgresConnectionString = 'postgresql+psycopg2://${postgresAdminUser}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/${postgresDb.name}?sslmode=require'

resource kvSecretJwt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'jwt-signing-key'
  properties: { value: jwtSigningKey }
}

resource kvSecretStorageConn 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'storage-connection-string'
  properties: { value: storageConnectionString }
}

resource kvSecretPgConn 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'database-url'
  properties: { value: postgresConnectionString }
}

resource kvSecretGoogleId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'google-oauth-client-id'
  properties: { value: googleOAuthClientId }
}

resource kvSecretGoogleSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'google-oauth-client-secret'
  properties: { value: googleOAuthClientSecret }
}

// ---------- App Service Plan + App Service -----------------------------------
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${namePrefix}-plan'
  location: location
  sku: {
    name: appServicePlanSku
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

resource appService 'Microsoft.Web/sites@2023-12-01' = {
  name: '${namePrefix}-app'
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      ftpsState: 'Disabled'
      alwaysOn: !startsWith(appServicePlanSku, 'F')
      minTlsVersion: '1.2'
      appCommandLine: 'gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=90 server.app:create_app()'
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'AZURE_STORAGE_CONNECTION_STRING'
          value: '@Microsoft.KeyVault(SecretUri=${kvSecretStorageConn.properties.secretUri})'
        }
        {
          name: 'AZURE_STORAGE_CONTAINER'
          value: mediaContainerName
        }
        {
          name: 'JWT_SIGNING_KEY'
          value: '@Microsoft.KeyVault(SecretUri=${kvSecretJwt.properties.secretUri})'
        }
        {
          name: 'DATABASE_URL'
          value: '@Microsoft.KeyVault(SecretUri=${kvSecretPgConn.properties.secretUri})'
        }
        {
          name: 'GOOGLE_OAUTH_CLIENT_ID'
          value: '@Microsoft.KeyVault(SecretUri=${kvSecretGoogleId.properties.secretUri})'
        }
        {
          name: 'GOOGLE_OAUTH_CLIENT_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=${kvSecretGoogleSecret.properties.secretUri})'
        }
        {
          name: 'FLASK_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=${kvSecretJwt.properties.secretUri})'
        }
        {
          name: 'TRUST_PROXY'
          value: '1'
        }
      ]
    }
  }
}

// ---------- RBAC --------------------------------------------------------------
// Built-in role definition IDs (unchanging GUIDs).
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

// Grant the App Service MSI Storage Blob Data Contributor on the storage account.
resource roleStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, appService.id, storageBlobDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: appService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Grant the App Service MSI Key Vault Secrets User.
resource roleKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, appService.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: appService.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Grant the human deployer Key Vault Secrets Officer so we can rotate secrets from the CLI.
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
resource roleKvDeployer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, deployerObjectId, keyVaultSecretsOfficerRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

// ---------- Outputs -----------------------------------------------------------
output appServiceHostname string = appService.properties.defaultHostName
output storageAccountName string = storage.name
output mediaContainerName string = mediaContainerName
output keyVaultName string = keyVault.name
output postgresFqdn string = postgres.properties.fullyQualifiedDomainName
output appInsightsConnectionString string = appInsights.properties.ConnectionString
