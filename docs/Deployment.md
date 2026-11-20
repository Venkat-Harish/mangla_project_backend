# Deployment: Azure Functions (Flex Consumption)

The FastAPI app runs inside one HTTP-triggered function. [function_app.py](../function_app.py) wraps `app.main:app` with `func.AsgiFunctionApp`, and [host.json](../host.json) sets an empty route prefix. The URLs are therefore the same as under uvicorn: `POST <host>/app/...`, as listed in [End-Points.md](End-Points.md).

| | |
|---|---|
| Function App | `mangla-project` (Flex Consumption, Linux, Python) |
| Region | South India |
| URL | `https://mangla-project-bfaec0ayddazhdcm.southindia-01.azurewebsites.net` |
| Instance memory | 512 MB |
| Maximum instances | 10 (caps cost, and keeps database connections under Supabase's pooler limit) |

## App settings
Set these under Function App → Settings → Environment variables.

| Name | Value |
|---|---|
| `DATABASE_URL` | Supabase **transaction pooler** connection string (port 6543). Azure can't reach the direct `db.<project>.supabase.co` host, which is IPv6-only. |
| `SUPABASE_URL` | `https://<project>.supabase.co` |
| `SUPABASE_SECRET_KEY` | Supabase secret key (Storage calls) |
| `MANGLA_AUDIT_BACKGROUND` | `false`: audit rows are written before the response. Functions doesn't guarantee the shutdown hook that flushes the background writer. |
| `MANGLA_LOGGER_PROPERTIES` | `logger.cloud.properties`: no log files, because the deployed folder is read-only. Lines go to Application Insights, masked. |

Any `app.properties` key can be overridden the same way, as `MANGLA_<KEY>` with dots written as underscores. An example is `MANGLA_CORS_ALLOW_ORIGINS`.

## CI/CD (GitHub Actions)
[.github/workflows/deploy.yml](../.github/workflows/deploy.yml) deploys every push to `main`, except pushes that only change docs. It can also be run by hand from the Actions tab.

1. **build** (no approval):
   - runs `tests/test_config.py`;
   - installs `requirements.txt` into `.python_packages/` on Linux with Python 3.14. Flex can't remote-build 3.14 yet.
2. **deploy** runs in the `production` environment:
   - It **waits for a required reviewer to approve** it.
   - It signs in to Azure with OIDC and deploys the package, minus everything [.funcignore](../.funcignore) lists.
   - It checks that an empty request to `/app/account/user-info` returns 422.

How it signs in (no stored password or secret):

| Piece | Value |
|---|---|
| Managed identity | `github-deployer-mangla` (user-assigned, resource group `food-service`) |
| Federated credential subject | `repo:Venkat-Harish@75791505/mangla_project_backend@1460410707:environment:production` (the repo uses GitHub's immutable-ID subject format) (issuer `https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange`) |
| Role | Website Contributor on the Function App `mangla-project` |
| GitHub environment `production` | Required reviewers, deployment branch `main`. Secrets `AZURE_CLIENT_ID` (the identity's client ID), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` |

Only a job running in the `production` environment of this repo can get the token. The environment's branch rule limits that to `main`.

## Publish by hand
From the backend root, signed in with `az login` to the tenant that holds the app:

```
func azure functionapp publish mangla-project --python
```

[.funcignore](../.funcignore) keeps tests, scripts, seed data, docs and `.env` out of the package.

## Run the Functions host locally
`local.settings.json` (git-ignored) holds `FUNCTIONS_WORKER_RUNTIME=python`. Secrets come from `.env` as usual.

```
func start
curl -X POST http://localhost:7071/app/home/kitchen-live -H "Content-Type: application/json" -d "{\"society_id\": \"<uuid>\"}"
```

## Cost and scaling
- **Billing:** Flex Consumption bills each execution for at least 1 second of instance memory. The monthly free grant is 100,000 GB-s and 250,000 executions per subscription.
- **Expected cost at 512 MB:** about $0/month for a ~300-flat society, ~$3 for ~1,000 flats, and ~$25 for a ~3,000-flat township.
- **Scaling up, in order:**
  1. Raise the maximum instance count.
  2. Move to 2,048 MB instances, which cost 4× per second but take more concurrent requests.
  3. Add one always-ready instance to remove cold starts (about $6.50/month at 512 MB).
- Set a budget alert in Cost Management.
