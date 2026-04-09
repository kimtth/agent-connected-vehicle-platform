@description('Azure region')
param location string = resourceGroup().location

@description('Prefix used to build resource names')
param namePrefix string = 'acvp'

@description('App Service Plan name (auto-derived from prefix if not supplied)')
param appServicePlanName string = '${namePrefix}-asp'

@description('App Service Plan SKU: { name, tier, size, capacity }')
param appServicePlanSku object

@description('Web App name (auto-derived from prefix if not supplied)')
param appServiceName string = '${namePrefix}-app'

@description('Private Link groupId for Cosmos (Sql | MongoDB | Cassandra | Gremlin | Table)')
param cosmosPrivateLinkGroupId string = 'Sql'

@description('Cosmos mode: existing = use provided resourceId, new = create account')
@allowed([
  'existing'
  'new'
])
param cosmosMode string = 'existing'

@description('Name for new Cosmos DB account (required when cosmosMode = new) (auto-derived if blank)')
param cosmosDbAccountName string = '${namePrefix}-cosmos'

@description('Resource ID of existing Cosmos DB account (required when cosmosMode = existing)')
param cosmosDbAccountResourceId string

@description('Virtual Network name (auto-derived from prefix if not supplied)')
param vnetName string = '${namePrefix}-vnet'

@description('Address space for the VNet')
param addressSpace string = '10.20.0.0/16'

@description('Delegated subnet (App Service VNet integration) name')
param subnetIntegrationName string

@description('CIDR for delegated integration subnet')
param subnetIntegrationPrefix string

@description('Private Endpoint subnet name')
param subnetPrivateEndpointName string

@description('CIDR for Private Endpoint subnet')
param subnetPrivateEndpointPrefix string

@description('Private Endpoint name for Cosmos DB (auto-derived from prefix if not supplied)')
param privateEndpointName string = '${namePrefix}-cosmos-pe'

@description('Whether to deploy Private DNS Zone for Cosmos')
param deployPrivateDnsZone bool = true

// ── AI Provider ─────────────────────────────────────────────────────
@description('Azure OpenAI endpoint (e.g. https://your-resource.openai.azure.com/)')
param azureOpenAiEndpoint string

@description('Azure OpenAI model deployment name')
param azureOpenAiModel string

@description('Azure OpenAI API version')
param azureOpenAiApiVersion string

@description('Resource ID of existing Azure OpenAI / Cognitive Services account (for RBAC)')
param azureOpenAiResourceId string = ''

// ── Azure Speech ────────────────────────────────────────────────────
@description('Azure Speech key')
@secure()
param azureSpeechKey string

@description('Azure Speech region (e.g. eastus)')
param azureSpeechRegion string = location

// ── Azure AD ────────────────────────────────────────────────────────
@description('Azure AD Tenant Id')
param azureTenantId string

@description('Azure AD Application (client) ID or Application ID URI exposed as API (api://...)')
param azureClientId string

@description('Web App public network access (Enabled | Disabled)')
@allowed([
  'Enabled'
  'Disabled'
])
param webAppPublicNetworkAccess string = 'Enabled'

@description('Deploy Private Endpoint to Cosmos (set false while testing)')
param enableCosmosPrivateEndpoint bool = true

@description('Optional user (object) Id to grant Cosmos DB Data Contributor (for troubleshooting). Leave blank to skip.')
param debugUserPrincipalId string = ''

// ── Variables ───────────────────────────────────────────────────────
var cosmosApiVersion = '2025-05-01-preview'
var privateDnsZoneName = 'privatelink.documents.azure.com'
var uniqueSuffix = toLower(substring(uniqueString(resourceGroup().id, namePrefix), 0, 6))
var appPlanNameEffective = '${appServicePlanName}-${uniqueSuffix}'
var webAppNameEffective = '${appServiceName}-${uniqueSuffix}'
var vnetNameEffective = '${vnetName}-${uniqueSuffix}'
var privateEndpointNameEffective = '${privateEndpointName}-${uniqueSuffix}'
var cosmosDbAccountNameEffective = '${cosmosDbAccountName}${uniqueSuffix}'

// Azure OpenAI RBAC: Cognitive Services OpenAI User
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// ── Cosmos DB ───────────────────────────────────────────────────────
resource cosmosNew 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' = if (cosmosMode == 'new') {
  name: cosmosDbAccountNameEffective
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    publicNetworkAccess: 'Disabled'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
}

var cosmosAccountName = cosmosMode == 'new' ? cosmosNew.name : last(split(cosmosDbAccountResourceId, '/'))
var cosmosAccountId = cosmosMode == 'new' ? cosmosNew.id : cosmosDbAccountResourceId

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' existing = {
  name: cosmosAccountName
}

var cosmosEndpoint = reference(cosmosAccountId, cosmosApiVersion).documentEndpoint

// ── Networking ──────────────────────────────────────────────────────
resource vnet 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: vnetNameEffective
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressSpace
      ]
    }
    subnets: [
      {
        name: subnetIntegrationName
        properties: {
          addressPrefix: subnetIntegrationPrefix
          delegations: [
            {
              name: 'webappDelegation'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: subnetPrivateEndpointName
        properties: {
          addressPrefix: subnetPrivateEndpointPrefix
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (deployPrivateDnsZone) {
  name: privateDnsZoneName
  location: 'global'
}

resource privateDnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (deployPrivateDnsZone) {
  name: '${vnet.name}-link'
  parent: privateDnsZone
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enableCosmosPrivateEndpoint) {
  name: privateEndpointNameEffective
  location: location
  properties: {
    subnet: {
      id: '${vnet.id}/subnets/${subnetPrivateEndpointName}'
    }
    privateLinkServiceConnections: [
      {
        name: 'cosmosDbConnection'
        properties: {
          privateLinkServiceId: cosmosAccountId
          groupIds: [
            cosmosPrivateLinkGroupId
          ]
          requestMessage: 'Access Cosmos DB via Private Endpoint'
        }
      }
    ]
  }
}

resource peDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (deployPrivateDnsZone && enableCosmosPrivateEndpoint) {
  name: 'default'
  parent: privateEndpoint
  properties: {
    privateDnsZoneConfigs: [
      {
        name: privateDnsZone.name
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
  dependsOn: [
    privateDnsVnetLink
  ]
}

// ── App Service ─────────────────────────────────────────────────────
resource plan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: appPlanNameEffective
  location: location
  sku: {
    name: appServicePlanSku.name
    tier: appServicePlanSku.tier
    size: appServicePlanSku.size
    capacity: appServicePlanSku.capacity
  }
  properties: {
    reserved: true
  }
}

resource webApp 'Microsoft.Web/sites@2024-11-01' = {
  name: webAppNameEffective
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: webAppPublicNetworkAccess
    virtualNetworkSubnetId: '${vnet.id}/subnets/${subnetIntegrationName}'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.13'
      appSettings: [
        // ── Azure OpenAI (managed identity – no API key) ──
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: azureOpenAiEndpoint
        }
        {
          name: 'AZURE_OPENAI_MODEL'
          value: azureOpenAiModel
        }
        {
          name: 'AZURE_OPENAI_API_VERSION'
          value: azureOpenAiApiVersion
        }

        // ── Azure Speech ──
        {
          name: 'AZURE_SPEECH_KEY'
          value: azureSpeechKey
        }
        {
          name: 'AZURE_SPEECH_REGION'
          value: azureSpeechRegion
        }

        // ── Cosmos DB (managed identity) ──
        {
          name: 'COSMOS_DB_ENDPOINT'
          value: cosmosEndpoint
        }
        {
          name: 'COSMOS_DB_USE_AAD'
          value: 'true'
        }
        {
          name: 'COSMOS_DB_DATABASE'
          value: 'VehiclePlatformDB'
        }

        // ── Azure AD Auth ──
        {
          name: 'AZURE_TENANT_ID'
          value: azureTenantId
        }
        {
          name: 'AZURE_CLIENT_ID'
          value: azureClientId
        }
        {
          name: 'AZURE_AUTH_REQUIRED'
          value: 'true'
        }

        // ── Platform runtime ──
        {
          name: 'MCP_SERVER_HOST'
          value: '127.0.0.1'
        }
        {
          name: 'ENABLE_MCP'
          value: 'true'
        }
      ]
      vnetRouteAllEnabled: true
    }
  }
  dependsOn: enableCosmosPrivateEndpoint ? [
    privateEndpoint
  ] : []
}

// ── RBAC: Cosmos DB Data Contributor → Web App ──────────────────────
resource cosmosDataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-12-01-preview' existing = {
  name: '00000000-0000-0000-0000-000000000002'
  parent: cosmosAccount
}

resource userToCosmosAccountScope 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-12-01-preview' = if (!empty(debugUserPrincipalId)) {
  name: guid('cosmosdb-userid', cosmosDataContributorRole.id, debugUserPrincipalId)
  parent: cosmosAccount
  properties: {
    roleDefinitionId: cosmosDataContributorRole.id
    principalId: debugUserPrincipalId
    scope: '/'
  }
}

resource webAppToCosmosAccountScope 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-12-01-preview' = {
  name: guid('cosmosdb-webapp', cosmosDataContributorRole.id, webApp.name)
  parent: cosmosAccount
  properties: {
    roleDefinitionId: cosmosDataContributorRole.id
    principalId: webApp.identity.principalId
    scope: '/'
  }
}

// ── RBAC: Azure OpenAI Cognitive Services OpenAI User → Web App ─────
resource openAiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(azureOpenAiResourceId)) {
  name: guid('openai-webapp', azureOpenAiResourceId, webApp.name, cognitiveServicesOpenAiUserRoleId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRoleId)
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Outputs ─────────────────────────────────────────────────────────
output webAppName string = webApp.name
output webAppDefaultHost string = webApp.properties.defaultHostName
output cosmosEndpointOut string = cosmosEndpoint
output webAppPrincipalId string = webApp.identity.principalId
@description('Azure region')
param location string = resourceGroup().location

@description('Prefix used to build resource names')
param namePrefix string = 'acvp'

@description('App Service Plan name (auto-derived from prefix if not supplied)')
param appServicePlanName string = '${namePrefix}-asp'

@description('App Service Plan SKU: { name, tier, size, capacity }')
param appServicePlanSku object

@description('Web App name (auto-derived from prefix if not supplied)')
param appServiceName string = '${namePrefix}-app'

@description('Private Link groupId for Cosmos (Sql | MongoDB | Cassandra | Gremlin | Table)')
param cosmosPrivateLinkGroupId string = 'Sql'

@description('Cosmos mode: existing = use provided resourceId, new = create account')
@allowed([
  'existing'
  'new'
])
param cosmosMode string = 'existing'

@description('Name for new Cosmos DB account (required when cosmosMode = new) (auto-derived if blank)')
param cosmosDbAccountName string = '${namePrefix}-cosmos'

@description('Resource ID of existing Cosmos DB account (required when cosmosMode = existing)')
param cosmosDbAccountResourceId string

@description('Virtual Network name (auto-derived from prefix if not supplied)')
param vnetName string = '${namePrefix}-vnet'

@description('Address space for the VNet')
param addressSpace string = '10.20.0.0/16'

@description('Delegated subnet (App Service VNet integration) name')
param subnetIntegrationName string

@description('CIDR for delegated integration subnet')
param subnetIntegrationPrefix string

@description('Private Endpoint subnet name')
param subnetPrivateEndpointName string

@description('CIDR for Private Endpoint subnet')
param subnetPrivateEndpointPrefix string

@description('Private Endpoint name for Cosmos DB (auto-derived from prefix if not supplied)')
param privateEndpointName string = '${namePrefix}-cosmos-pe'

@description('Whether to deploy Private DNS Zone for Cosmos')
param deployPrivateDnsZone bool = true

@description('Azure OpenAI endpoint (e.g. https://your-azure-openai-resource.openai.azure.com/ )')
param azureOpenAiEndpoint string

@description('Azure OpenAI deployment name')
param azureOpenAiDeploymentName string

@description('Azure OpenAI API version')
param azureOpenAiApiVersion string

@description('Azure OpenAI API key')
@secure()
param azureOpenAiApiKey string

@description('Azure Speech key')
@secure()
param azureSpeechKey string

@description('Azure Speech region (e.g. eastus)')
param azureSpeechRegion string = location

@description('Optional fallback OpenAI API key (leave empty if unused)')
@secure()
param openAiApiKey string = ''

@description('Optional fallback OpenAI chat model name')
param openAiChatModelName string = ''

@description('Azure AD Tenant Id')
param azureTenantId string

@description('Azure AD Application (client) ID or Application ID URI exposed as API (api://...)')
param azureClientId string

@description('Web App public network access (Enabled | Disabled)')
@allowed([
  'Enabled'
  'Disabled'
])
param webAppPublicNetworkAccess string = 'Enabled'

@description('Deploy Private Endpoint to Cosmos (set false while testing or until correct Cosmos ID supplied)')
param enableCosmosPrivateEndpoint bool = true

// User ID: Get your principal User Id (Object ID) from Entra ID (formerly Azure AD) - for troubleshooting purposes
@description('Optional user (object) Id to grant Cosmos DB Data Contributor (for troubleshooting). Leave blank to skip.')
param debugUserPrincipalId string = ''

// Variables
var cosmosApiVersion = '2025-05-01-preview'
var privateDnsZoneName = 'privatelink.documents.azure.com'

// === Added uniqueness helpers ===
var uniqueSuffix = toLower(substring(uniqueString(resourceGroup().id, namePrefix), 0, 6))

// Effective resource names (DNS zone unchanged intentionally)
var appPlanNameEffective = '${appServicePlanName}-${uniqueSuffix}'
var webAppNameEffective = '${appServiceName}-${uniqueSuffix}'
var vnetNameEffective = '${vnetName}-${uniqueSuffix}'
var privateEndpointNameEffective = '${privateEndpointName}-${uniqueSuffix}'
// Cosmos account: avoid extra dash in case of stricter naming rules
var cosmosDbAccountNameEffective = '${cosmosDbAccountName}${uniqueSuffix}'

// Using the provided Cosmos DB account resource ID when cosmosMode == 'existing' (no local 'existing' resource declaration needed)

// New Cosmos DB account (only when cosmosMode == new)
resource cosmosNew 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' = if (cosmosMode == 'new') {
  name: cosmosDbAccountNameEffective
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    publicNetworkAccess: 'Disabled' // force private access only
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
}

// === Added helper for Cosmos account name & existing reference ===
var cosmosAccountName = cosmosMode == 'new' ? cosmosNew.name : last(split(cosmosDbAccountResourceId, '/'))

// Resolve the full resource id for the Cosmos account depending on mode
var cosmosAccountId = cosmosMode == 'new' ? cosmosNew.id : cosmosDbAccountResourceId

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' existing = {
  name: cosmosAccountName
}

// Unified Cosmos variables
var cosmosEndpoint = reference(cosmosAccountId, cosmosApiVersion).documentEndpoint
var cosmosPrimaryKey = listKeys(cosmosAccountId, cosmosApiVersion).primaryMasterKey

// Networking
resource vnet 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: vnetNameEffective
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressSpace
      ]
    }
    subnets: [
      {
        name: subnetIntegrationName
        properties: {
          addressPrefix: subnetIntegrationPrefix
          delegations: [
            {
              name: 'webappDelegation'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: subnetPrivateEndpointName
        properties: {
          addressPrefix: subnetPrivateEndpointPrefix
          // Disable network policies for Private Endpoint
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

// Optional Private DNS Zone
resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (deployPrivateDnsZone) {
  name: privateDnsZoneName
  location: 'global'
}

resource privateDnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (deployPrivateDnsZone) {
  name: '${vnet.name}-link'
  parent: privateDnsZone
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

// Private Endpoint for Cosmos
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = if (enableCosmosPrivateEndpoint) {
  name: privateEndpointNameEffective
  location: location
  properties: {
    subnet: {
      id: '${vnet.id}/subnets/${subnetPrivateEndpointName}'
    }
    privateLinkServiceConnections: [
      {
        name: 'cosmosDbConnection'
        properties: {
          privateLinkServiceId: cosmosAccountId
          groupIds: [
            cosmosPrivateLinkGroupId
          ]
          requestMessage: 'Access Cosmos DB via Private Endpoint'
        }
      }
    ]
  }
}

// Associate Private DNS zone to PE (creates A record) if enabled
resource peDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = if (deployPrivateDnsZone && enableCosmosPrivateEndpoint) {
  name: 'default'
  parent: privateEndpoint
  properties: {
    privateDnsZoneConfigs: [
      {
        name: privateDnsZone.name
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
  dependsOn: [
    privateDnsVnetLink
  ]
}

// App Service Plan
resource plan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: appPlanNameEffective
  location: location
  sku: {
    name: appServicePlanSku.name
    tier: appServicePlanSku.tier
    size: appServicePlanSku.size
    capacity: appServicePlanSku.capacity
  }
  properties: {
    reserved: true // If Linux app service plan <code>true</code>, <code>false</code> otherwise.
  }
}

// Web App (public by default)
resource webApp 'Microsoft.Web/sites@2024-11-01' = {
  name: webAppNameEffective
  location: location
  kind: 'app,linux'
  identity: {          // Added identity for Cosmos RBAC
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: webAppPublicNetworkAccess
    virtualNetworkSubnetId: '${vnet.id}/subnets/${subnetIntegrationName}'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appSettings: [
        // === Azure OpenAI primary (preferred) ===
        {
          name: 'AZURE_OPENAI_API_KEY'
          value: azureOpenAiApiKey
        }
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: azureOpenAiEndpoint
        }
        {
          name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
          value: azureOpenAiDeploymentName
        }
        {
          name: 'AZURE_OPENAI_API_VERSION'
          value: azureOpenAiApiVersion
        }

        // === Azure Speech ===
        {
          name: 'AZURE_SPEECH_KEY'
          value: azureSpeechKey
        }
        {
          name: 'AZURE_SPEECH_REGION'
          value: azureSpeechRegion
        }

        // === OpenAI fallback (optional) ===
        {
          name: 'OPENAI_API_KEY'
          value: openAiApiKey
        }
        {
          name: 'OPENAI_CHAT_MODEL_NAME'
          value: openAiChatModelName
        }

        // === Cosmos DB (existing primary key already present; add alias & containers) ===
        {
          name: 'COSMOS_DB_ENDPOINT'
          value: cosmosEndpoint
        }
        {
          name: 'COSMOS_DB_KEY'
          value: cosmosPrimaryKey
        }
        {
          name: 'COSMOS_DB_DATABASE'
          value: 'VehiclePlatformDB'
        }
        {
          name: 'COSMOS_DB_CONTAINER_VEHICLES'
          value: 'vehicles'
        }
        {
          name: 'COSMOS_DB_CONTAINER_SERVICES'
          value: 'services'
        }
        {
          name: 'COSMOS_DB_CONTAINER_COMMANDS'
          value: 'commands'
        }
        {
          name: 'COSMOS_DB_CONTAINER_NOTIFICATIONS'
          value: 'notifications'
        }
        {
          name: 'COSMOS_DB_CONTAINER_STATUS'
          value: 'vehiclestatus'
        }
        {
          name: 'COSMOS_DB_USE_AAD'
          value: 'true'
        }
        // === Azure AD Auth ===
        {
          name: 'AZURE_TENANT_ID'
          value: azureTenantId
        }
        // Using Application ID URI (api://...) if supplied; otherwise raw client id
        {
          name: 'AZURE_CLIENT_ID'
          value: 'api://${azureClientId}' // assuming api://... format
        }
        {
          name: 'AZURE_AUTH_REQUIRED'
          value: 'true'
        }
        // === App & Platform runtime flags ===
        {
          name: 'MCP_SERVER_HOST'
          value: '127.0.0.1'
        }
        {
          name: 'ENABLE_MCP'
          value: 'true'
        }
      ]
      vnetRouteAllEnabled: true
    }
  }
  dependsOn: enableCosmosPrivateEndpoint ? [
    privateEndpoint
  ] : []
}

// Cosmos DB Data-plane built-in role reference
resource cosmosDataContributorRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-12-01-preview' existing = {
  name: '00000000-0000-0000-0000-000000000002' // Built-in Data Contributor
  parent: cosmosAccount
}

// Assign Data Contributor to a debug user (only if principal supplied)
resource userToCosmosAccountScope 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-12-01-preview' = if (!empty(debugUserPrincipalId)) {
  name: guid('cosmosdb-userid', cosmosDataContributorRole.id, debugUserPrincipalId)
  parent: cosmosAccount
  properties: {
    roleDefinitionId: cosmosDataContributorRole.id
    principalId: debugUserPrincipalId
    scope: '/' // account-level
  }
}

// Assign Data Contributor to the Web App managed identity
resource webAppToCosmosAccountScope 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-12-01-preview' = {
  name: guid('cosmosdb-webapp', cosmosDataContributorRole.id, webApp.name)
  parent: cosmosAccount
  properties: {
    roleDefinitionId: cosmosDataContributorRole.id
    principalId: webApp.identity.principalId
    scope: '/'
  }
}

// Outputs
output webAppName string = webApp.name
output webAppDefaultHost string = webApp.properties.defaultHostName
output cosmosEndpointOut string = cosmosEndpoint
