# FlowShield Deployment Guide
This guide provides instructions on staging, containerizing, and deploying **FlowShield** to **IBM Cloud** (via IBM Cloud Code Engine or IBM Cloud Foundry).

---

## 1. Environment & API Credentials
Before deploying, make sure you have your IBM Cloud credentials ready. FlowShield connects to IBM Granite models hosted on IBM Cloud.

Prepare a deployment `.env` file (copied from `.env.example`):
```bash
GRANITE_API_URL=https://us-south.ml.cloud.ibm.com
GRANITE_API_KEY=<your-ibm-cloud-api-key>
GRANITE_MODEL_ID=ibm/granite-3-8b-instruct
```

*Note:* If `GRANITE_API_KEY` is not set, FlowShield will degrade gracefully and run utilizing its deterministic logic.

---

## 2. In-Service Health Checks
FlowShield features a dedicated JSON health-check endpoint on the server instance:
- **Port Location:** Default port is `8080` (or dynamically mapped using the container `$PORT` env variable).
- **Paths:** `/health` or `/api/health`
- **Output Sample:**
```json
{
  "status": "healthy",
  "service": "flowshield-command-dashboard"
}
```

This endpoint is compatible with IBM Cloud Code Engine HTTP ping checks, Kubernetes readiness/liveness probes, and load balancer ping configs.

---

## 3. Deployment Option A: IBM Cloud Code Engine (Recommended)
IBM Code Engine is a fully managed, serverless container hosting platform.

### Step 3.1: Log in to IBM Cloud CLI
Ensure you have the IBM Cloud CLI and Code Engine plugins installed:
```bash
# Login to IBM Cloud
ibmcloud login --sso

# Configure target region (e.g. us-south)
ibmcloud target -r us-south -g Default
```

### Step 3.2: Build and Push Docker image
1. Target your IBM Cloud Container Registry namespace (create one if necessary):
   ```bash
   ibmcloud cr login
   ibmcloud cr namespace-add flowshield-scope
   ```
2. Build and push the container image:
   ```bash
   # Build image locally
   docker build -t us.icr.io/flowshield-scope/flowshield-dashboard:latest .

   # Push to IBM Registry
   docker push us.icr.io/flowshield-scope/flowshield-dashboard:latest
   ```

### Step 3.3: Deploy to Code Engine
1. Target or create a Code Engine project:
   ```bash
   ibmcloud ce project create --name flowshield-project
   ibmcloud ce project select --name flowshield-project
   ```
2. Deploy the application:
   ```bash
   ibmcloud ce app create --name flowshield-app \
     --image us.icr.io/flowshield-scope/flowshield-dashboard:latest \
     --env GRANITE_API_KEY=<your-api-key> \
     --env GRANITE_API_URL=https://us-south.ml.cloud.ibm.com \
     --env GRANITE_MODEL_ID=ibm/granite-3-8b-instruct \
     --port 8080 \
     --min-scale 1 \
     --max-scale 3
   ```
3. Once running, Code Engine will provide a secure HTTPS route mapping directly to your dashboard.

---

## 4. Deployment Option B: IBM Cloud Foundry v2
If you are deploying using Cloud Foundry buildpacks, use the pre-configured `manifest.yml`:

Deploy utilizing the Cloud Foundry CLI:
```bash
# Target your CF space
ibmcloud target --cf

# Deploy application instance
ibmcloud cf push
```

The config automatically targets the Python Buildpack, installs `requirements.txt` dependencies, routes inbound traffic dynamically, and starts `scripts/serve_dashboard.py` on the assigned system port.
