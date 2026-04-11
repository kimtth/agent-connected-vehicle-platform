@description('Assignment kind to create.')
@allowed([
  'cognitive'
  'cosmosSql'
])
param assignmentKind string

@description('Name of the target account in this resource group.')
param accountName string

@description('Principal ID to grant the role to.')
param principalId string

@description('Role definition GUID. Use the Azure RBAC role definition ID for cognitive assignments or the Cosmos SQL role definition ID for cosmosSql assignments.')
param roleDefinitionId string

@description('Optional fixed GUID for the role assignment name.')
param roleAssignmentName string = ''

resource cognitiveAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (assignmentKind == 'cognitive') {
  name: accountName
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2025-05-01-preview' existing = if (assignmentKind == 'cosmosSql') {
  name: accountName
}

resource cosmosRoleDefinition 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-12-01-preview' existing = if (assignmentKind == 'cosmosSql') {
  name: roleDefinitionId
  parent: cosmosAccount
}

var assignmentName = !empty(roleAssignmentName)
  ? roleAssignmentName
  : assignmentKind == 'cognitive'
      ? guid('cog-rbac', cognitiveAccount.id, principalId, roleDefinitionId)
      : guid('cosmosdb-rbac', cosmosRoleDefinition.id, principalId)

resource cognitiveRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignmentKind == 'cognitive') {
  name: assignmentName
  scope: cognitiveAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-12-01-preview' = if (assignmentKind == 'cosmosSql') {
  name: assignmentName
  parent: cosmosAccount
  properties: {
    roleDefinitionId: cosmosRoleDefinition.id
    principalId: principalId
    scope: cosmosAccount.id
  }
}
