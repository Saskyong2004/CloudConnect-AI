# CloudConnect AI – Deployment Guide (upgrade your existing AWS project)

Region: **ap-south-1 (Mumbai)** – same as your current project.
Nothing existing is thrown away: same S3 bucket, same API, same DynamoDB table (`ContactMessages`).

## What changed

| Area | Before | Now |
|---|---|---|
| Lambda | writes name/email/message | validates input, **AI analysis (Amazon Comprehend)**, timestamp, status, priority, and handles **all CRUD routes** |
| API Gateway | `POST /contact` | + `GET /messages`, `GET /messages/{id}`, `PUT /messages/{id}`, `DELETE /messages/{id}` |
| DynamoDB | id, name, email, message | + createdAt, status, priority, sentiment, sentimentScores, category, keyPhrases, language, adminNote, updatedAt |
| IAM | AmazonDynamoDBFullAccess | **least-privilege** policy (`backend/iam-policy.json`) |
| Generative AI | none | **Google Gemini API**: one-line summary + suggested reply draft for each message |
| Frontend | `index.html` | updated `index.html`, new `admin.html` dashboard, `config.js` |

## Step 1 – IAM (least privilege)
1. IAM → Roles → open the role used by `serverless-contact-form`.
2. **Remove** `AmazonDynamoDBFullAccess`.
3. Add inline policy → JSON → paste `backend/iam-policy.json`.
   Replace `YOUR_ACCOUNT_ID` with your 12-digit account ID (the SNS statement is only needed if you do Step 6).
4. Keep `AWSLambdaBasicExecutionRole` (CloudWatch logs).

## Step 2 – Lambda
1. Lambda → `serverless-contact-form` → Code tab → replace the code with `backend/lambda_function.py` → **Deploy**.
2. Configuration → Environment variables:
   - `TABLE_NAME` = `ContactMessages`
   - `ADMIN_KEY` = a long random secret (e.g. 20+ characters). This is the admin dashboard password.
3. Configuration → General → set Timeout to **30 seconds** (default 3 s is too short for the AI calls).
4. Optional env vars: `ENABLE_GENAI` = `false` turns generative AI off; `GEMINI_API_KEY` and `GEMINI_MODEL` are explained in Step 5b.
5. Make sure the Lambda handler is `lambda_function.lambda_handler`.

## Step 3 – API Gateway routes
Open API `Serverless-Contact-API` → Routes → Create, and attach the **same Lambda integration** to each:

- `POST /contact` (already exists)
- `GET /messages`
- `GET /messages/{id}`
- `PUT /messages/{id}`
- `DELETE /messages/{id}`

Then CORS (API → CORS → Configure):
- Access-Control-Allow-Origin: your S3 website URL (or `*` for the demo)
- Access-Control-Allow-Methods: `GET, POST, PUT, DELETE, OPTIONS`
- Access-Control-Allow-Headers: `content-type, x-admin-key`

Deploy (HTTP APIs with `$default` stage auto-deploy). Optional: Stages → Throttling, e.g. 10 req/s, burst 20.

## Step 4 – Frontend to S3
1. Check `frontend/config.js` – `API_BASE` is already your current API URL.
2. Upload **all** files from `frontend/` to your S3 bucket: `index.html`, `admin.html`, `style.css`, `admin.css`, `script.js`, `admin.js`, `config.js`.
3. Open the S3 website URL; the **Admin** link is in the navbar.

## Step 5 – Test (collect these screenshots for the report)
1. Submit a **negative** message on the site ("The app keeps crashing, this is terrible") → success message shows AI result.
2. Submit a **positive** one ("Great service, thank you!").
3. DynamoDB → Explore items → show the new fields (sentiment, category, keyPhrases...).
4. Open `admin.html`, enter your `ADMIN_KEY` → messages and stats appear.
5. Change a status (PUT), delete a message (DELETE).
6. Try a wrong admin key → **401 Unauthorized** (security evidence).
7. Lambda → Monitor → CloudWatch logs.

Command-line checks (replace values):
```
API=https://5u71iy0sw3.execute-api.ap-south-1.amazonaws.com
curl -X POST $API/contact -H "Content-Type: application/json" \
  -d '{"name":"Test","email":"t@example.com","message":"The app crashes, terrible!"}'
curl $API/messages -H "x-admin-key: YOUR_KEY"
curl -X PUT $API/messages/<id> -H "x-admin-key: YOUR_KEY" -H "Content-Type: application/json" -d '{"status":"Resolved"}'
curl -X DELETE $API/messages/<id> -H "x-admin-key: YOUR_KEY"
```

## Step 5b – Generative AI (Google Gemini API, free tier)
1. Go to https://aistudio.google.com and sign in with a Google account.
2. Click **Get API key → Create API key**. Copy it (starts with `AIza...`). No billing account is needed for the free tier.
3. Lambda → Configuration → Environment variables → add:
   - `GEMINI_API_KEY` = your key
   - `ENABLE_GENAI` = `true`
   - `GEMINI_MODEL` = **leave it out** (recommended). The code automatically uses Google's `gemini-flash-lite-latest` / `gemini-flash-latest` names, so it keeps working when model names change. Only set it if you want a specific model that exists in AI Studio.
4. Send a test message. The dashboard should show an "AI summary" and a "Suggested reply".
5. If nothing shows, open the Lambda CloudWatch logs and look for `Gemini generation failed:` – it prints the HTTP code (400 bad request, 403/401 bad key, 404 wrong model name, 429 free-tier limit reached).
- The key lives only in a Lambda environment variable (never in the website files). For production use AWS Secrets Manager.
- Free-tier limits apply; if exceeded the message is still saved, just without summary/reply.
- The reply is only a **draft** shown to the admin. Nothing is emailed to the customer automatically.
- Privacy: the message text is sent to Google's Gemini API. Say this in your report.

## If Amazon Comprehend is not allowed on your account
Some new/free AWS accounts get `SubscriptionRequiredException` for Comprehend in the Lambda logs. The app handles this automatically:
sentiment and key phrases then come from **Gemini** instead (saved as `sentimentSource: "gemini"`; normally `"comprehend"`).
Fix it permanently by finishing account activation / upgrading from the Free plan, then Comprehend is used again. State which one was used in your report.

## Step 6 – Optional: email alert for negative feedback
1. SNS → Create topic `cloudconnect-alerts` → create an **Email** subscription → confirm the email.
2. Lambda env var `SNS_TOPIC_ARN` = the topic ARN. (Policy already has the `sns:Publish` statement.)

## Local tests (no AWS needed)
```
cd backend
python3 -m unittest discover -s tests
```

## Known limitations (state these honestly in the report)
- Category is keyword-rule based; Comprehend provides sentiment and key phrases; Gemini writes the summary and draft reply (AI text can be wrong, so an admin reviews it).
- The admin key is a shared secret – fine for a demo; production should use Amazon Cognito.
- `GET /messages` uses a DynamoDB Scan – fine for small data; use pagination/GSI at scale.
- The S3 website endpoint is HTTP only; use CloudFront for HTTPS and a custom domain.
