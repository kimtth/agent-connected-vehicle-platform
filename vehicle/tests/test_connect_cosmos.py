import os
from azure.cosmos import CosmosClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

load_dotenv(override=True)

endpoint = os.getenv("COSMOS_DB_ENDPOINT")

try:
    # credential = DefaultAzureCredential()

    # Development
    credential = AzureCliCredential(tenant_id=os.getenv("AZURE_TENANT_ID"))
    token = credential.get_token("https://management.azure.com/.default")
    print(token.token)

    # Production 
    # credential = ManagedIdentityCredential()

    client = CosmosClient(endpoint, credential=credential)

    container = client.get_database_client(os.getenv("COSMOS_DB_DATABASE")).get_container_client(os.getenv("COSMOS_DB_CONTAINER_VEHICLES"))

    print("Connected to Azure Cosmos DB successfully.")
except Exception as e:
    print(f"Failed to connect to Azure Cosmos DB: {e}")