# Deploying to Google Cloud Run

This guide provides step-by-step instructions for deploying the No-Code Architects Toolkit API to Google Cloud Run.

## Prerequisites

- A Google Cloud account. [Sign up here](https://cloud.google.com/) if you don't already have one.
  - New users receive $300 in free credits.
- Google Cloud SDK installed on your local machine. [Installation guide](https://cloud.google.com/sdk/docs/install)
- Docker installed on your local machine. [Installation guide](https://docs.docker.com/get-docker/)

## Step 1: Create a Google Cloud Project

1. Log into the [GCP Console](https://console.cloud.google.com/).
2. Click on the **Project Selector** in the top navigation bar and select **New Project**.
3. Enter a project name, such as `NCA Toolkit Project`.
4. Click **Create**.

## Step 2: Enable Required APIs

Enable the following APIs:
- **Cloud Storage API**
- **Cloud Storage JSON API**
- **Cloud Run API**

### How to Enable APIs:
1. In the GCP Console, navigate to **APIs & Services** > **Enable APIs and Services**.
2. Search for each API, click on it, and enable it.

## Step 3: Create a Service Account

1. Navigate to **IAM & Admin** > **Service Accounts** in the GCP Console.
2. Click **+ Create Service Account**.
   - Enter a name (e.g., `NCA Toolkit Service Account`).
3. Assign the following roles to the service account:
   - **Storage Admin**
   - **Viewer**
4. Click **Done** to create the service account.
5. Open the service account details and navigate to the **Keys** tab.
   - Click **Add Key** > **Create New Key**.
   - Choose **JSON** format, download the file, and store it securely.

## Step 4: Create a Cloud Storage Bucket

1. Navigate to **Storage** > **Buckets** in the GCP Console.
2. Click **+ Create Bucket**.
   - Choose a unique bucket name (e.g., `nca-toolkit-bucket`).
   - Leave default settings, but:
     - Uncheck **Enforce public access prevention**.
     - Set **Access Control** to **Uniform**.
3. Click **Create** to finish.
4. Go to the bucket permissions, and add **allUsers** as a principal with the role:
   - **Storage Object Viewer**.
5. Save changes.

## Step 5: Deploy on Google Cloud Run

### Option 1: Deploy using Google Cloud Console

1. Navigate to **Cloud Run** in the Google Cloud Console.
2. Click **Create Service**.
3. Choose **Deploy one revision from an existing container image**.
4. Click **Browse** and select the Docker Hub image:
   ```
   stephengpope/no-code-architects-toolkit:latest
   ```
   Or use your own image if you've built and pushed one.
5. Configure the service:
   - Set **Service name**: `no-code-architects-toolkit`
   - Set **Region**: Choose a region close to your users
   - Set **Authentication**: Allow unauthenticated invocations
6. Configure advanced settings:
   - Set **Memory**: `16 GB`
   - Set **CPU**: `4 CPUs`
   - Set **CPU Allocation**: Always allocated
   - Set **Minimum instances**: `0`
   - Set **Maximum instances**: `5`
   - Set **Request timeout**: `300 seconds`
   - Set **Container port**: `8080`
7. Add environment variables:
   - `API_KEY`: Your API key (e.g., `Test123`)
   - `GCP_BUCKET_NAME`: The name of your Cloud Storage bucket
   - `GCP_SA_CREDENTIALS`: The JSON key of your service account (paste the entire contents)
8. Click **Create** to deploy the service.

### Option 2: Deploy using Google Cloud SDK (Command Line)

1. Authenticate with Google Cloud:
   ```bash
   gcloud auth login
   ```

2. Set your project ID:
   ```bash
   gcloud config set project YOUR_PROJECT_ID
   ```

3. Build and push the Docker image to Google Container Registry:
   ```bash
   docker build -t gcr.io/YOUR_PROJECT_ID/no-code-architects-toolkit .
   docker push gcr.io/YOUR_PROJECT_ID/no-code-architects-toolkit
   ```

4. Deploy to Cloud Run:
   ```bash
   gcloud run deploy no-code-architects-toolkit \
     --image gcr.io/YOUR_PROJECT_ID/no-code-architects-toolkit \
     --platform managed \
     --region YOUR_REGION \
     --allow-unauthenticated \
     --memory 16Gi \
     --cpu 4 \
     --cpu-always-allocated \
     --min-instances 0 \
     --max-instances 5 \
     --timeout 300s \
     --set-env-vars "API_KEY=YOUR_API_KEY,GCP_BUCKET_NAME=YOUR_BUCKET_NAME,GCP_SA_CREDENTIALS=$(cat path/to/service-account-key.json | jq -c)"
   ```

## Step 6: Test the Deployment

1. After deployment, you'll receive a URL for your service.
2. Test the API using a tool like Postman or curl:
   ```bash
   curl -X GET "YOUR_SERVICE_URL/v1/toolkit/test" \
     -H "x-api-key: YOUR_API_KEY"
   ```

3. You should receive a response indicating the API is working correctly.

## Troubleshooting

- **Deployment Fails**: Check the logs in the Google Cloud Console for error messages.
- **API Returns Errors**: Verify that all environment variables are set correctly.
- **Storage Issues**: Ensure the service account has the correct permissions for the storage bucket.
- **Memory/CPU Errors**: You might need to increase the allocated resources if processing large media files.

## Monitoring and Maintenance

- Monitor your service using Google Cloud Monitoring.
- Set up alerts for high CPU usage, memory usage, or error rates.
- Regularly update the Docker image with security patches and new features.
