# GitHub Repository Setup with CI/CD

This guide will help you set up your GitHub repository with CI/CD for automatic deployment to Google Cloud Run.

## 1. Create a GitHub Repository

1. Go to [GitHub](https://github.com) and sign in to your account.
2. Click on the "+" icon in the top-right corner and select "New repository".
3. Enter a name for your repository (e.g., "no-code-architects-toolkit").
4. Choose whether you want the repository to be public or private.
5. Click "Create repository".

## 2. Push Your Code to GitHub

After creating the repository, you'll see instructions on how to push your existing repository. Follow these commands:

```bash
git remote add origin https://github.com/YOUR_USERNAME/no-code-architects-toolkit.git
git branch -M main
git add .
git commit -m "Initial commit"
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

## 3. Set Up GitHub Secrets

For the CI/CD workflow to work, you need to set up the following secrets in your GitHub repository:

1. Go to your repository on GitHub.
2. Click on "Settings" > "Secrets and variables" > "Actions".
3. Click on "New repository secret" and add the following secrets:

   - **GCP_PROJECT_ID**: Your Google Cloud Project ID
   - **GCP_SA_KEY**: The JSON key of your Google Cloud Service Account (the entire JSON content)
   - **API_KEY**: The API key you want to use for your application
   - **GCP_BUCKET_NAME**: The name of your Google Cloud Storage bucket
   - **GCP_SA_CREDENTIALS**: The JSON credentials for your Google Cloud Service Account (same as GCP_SA_KEY)

## 4. Create a Service Account for GitHub Actions

1. In the Google Cloud Console, navigate to "IAM & Admin" > "Service Accounts".
2. Click "Create Service Account".
3. Enter a name (e.g., "github-actions").
4. Assign the following roles:
   - Cloud Run Admin
   - Storage Admin
   - Service Account User
   - Cloud Build Service Account
5. Create a JSON key for this service account and download it.
6. Copy the entire content of this JSON file and paste it as the value for both the `GCP_SA_KEY` and `GCP_SA_CREDENTIALS` secrets in GitHub.

## 5. Enable Required APIs

Make sure the following APIs are enabled in your Google Cloud project:

- Cloud Run API
- Cloud Build API
- Container Registry API
- Cloud Storage API

## 6. Trigger the Workflow

The workflow will automatically run when you push to the `main` branch. You can also manually trigger it:

1. Go to your repository on GitHub.
2. Click on "Actions".
3. Select the "Build and Deploy to Google Cloud Run" workflow.
4. Click "Run workflow" > "Run workflow".

## 7. Monitor the Deployment

1. Go to your repository on GitHub.
2. Click on "Actions".
3. Click on the latest workflow run.
4. You can see the progress and logs of each step.
5. Once completed, the URL of your deployed application will be shown in the "Show Output" step.
