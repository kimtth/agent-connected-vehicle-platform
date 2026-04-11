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
@description('Resource ID of existing Azure Speech / Cognitive Services account (for RBAC)')
param azureSpeechResourceId string = ''

@description('Azure Speech endpoint (custom subdomain, e.g. https://my-speech.cognitiveservices.azure.com)')
param azureSpeechEndpoint string = ''

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

// Azure Speech RBAC: Cognitive Services User (required for STS token issuance)
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

// Cosmos DB SQL RBAC: Built-in Data Contributor
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

// Parsed segments from azureOpenAiResourceId for cross-RG module scope
var openAiSubId = !empty(azureOpenAiResourceId) ? split(azureOpenAiResourceId, '/')[2] : subscription().subscriptionId
var openAiRgName = !empty(azureOpenAiResourceId) ? split(azureOpenAiResourceId, '/')[4] : resourceGroup().name
var openAiAccountName = !empty(azureOpenAiResourceId) ? last(split(azureOpenAiResourceId, '/')) : 'none'

// Parsed segments from azureSpeechResourceId for cross-RG module scope
var speechSubId = !empty(azureSpeechResourceId) ? split(azureSpeechResourceId, '/')[2] : subscription().subscriptionId
var speechRgName = !empty(azureSpeechResourceId) ? split(azureSpeechResourceId, '/')[4] : resourceGroup().name
var speechAccountName = !empty(azureSpeechResourceId) ? last(split(azureSpeechResourceId, '/')) : 'none'

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
      appCommandLine: 'python main.py'
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

        // ── Azure Speech (managed identity – no API key) ──
        {
          name: 'AZURE_SPEECH_REGION'
          value: azureSpeechRegion
        }
        {
          name: 'AZURE_SPEECH_ENDPOINT'
          value: azureSpeechEndpoint
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

module cosmosUserRbac 'modules/cognitive-rbac.bicep' = if (!empty(debugUserPrincipalId)) {
  params: {
    assignmentKind: 'cosmosSql'
    accountName: cosmosAccountName
    principalId: debugUserPrincipalId
    roleDefinitionId: cosmosDataContributorRoleId
  }
}

module cosmosWebAppRbac 'modules/cognitive-rbac.bicep' = {
  params: {
    assignmentKind: 'cosmosSql'
    accountName: cosmosAccountName
    principalId: webApp.identity.principalId
    roleDefinitionId: cosmosDataContributorRoleId
  }
}

module openAiRbac 'modules/cognitive-rbac.bicep' = if (!empty(azureOpenAiResourceId)) {
  scope: resourceGroup(openAiSubId, openAiRgName)
  params: {
    assignmentKind: 'cognitive'
    accountName: openAiAccountName
    principalId: webApp.identity.principalId
    roleDefinitionId: cognitiveServicesOpenAiUserRoleId
  }
}

module speechRbac 'modules/cognitive-rbac.bicep' = if (!empty(azureSpeechResourceId)) {
  scope: resourceGroup(speechSubId, speechRgName)
  params: {
    assignmentKind: 'cognitive'
    accountName: speechAccountName
    principalId: webApp.identity.principalId
    roleDefinitionId: cognitiveServicesUserRoleId
  }
}

// ── Outputs ─────────────────────────────────────────────────────────
output webAppName string = webApp.name
output webAppDefaultHost string = webApp.properties.defaultHostName
output cosmosEndpointOut string = cosmosEndpoint
output webAppPrincipalId string = webApp.identity.principalId
