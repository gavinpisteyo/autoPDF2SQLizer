#!/bin/bash
# =============================================================================
# Deploy to Azure App Service
# =============================================================================
# Builds the React frontend, then deploys everything to Azure.
# Run from the project root: ./deploy.sh
# =============================================================================

set -euo pipefail

echo "Building frontend..."
cd frontend && npm run build && cd ..

echo "Deploying to Azure..."
az webapp up --name autopdf2sqlizer --resource-group n8n-AI-Automations --location centralus

echo ""
echo "Deployed to: https://autopdf2sqlizer.azurewebsites.net"
