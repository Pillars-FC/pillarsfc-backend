# Pillars Football Club (Pillars FC) Backend

The backend API for the Pillars Football Club website. It provides public club information, member services, event subscriptions, Player of the Month polling, news publishing, and admin endpoints.

## Technology

- Python 3.12 (recommended)
- FastAPI and Pydantic for the API and request validation
- PyMongo's asynchronous `AsyncMongoClient` for MongoDB
- Cloudinary for profile and news images
- Resend for contact and member-account emails
- SlowAPI for request rate limiting
- Pytest and HTTPX for API tests
- Ruff for Python linting and formatting

## Clone the repository

Replace `ACCOUNT` and `REPOSITORY` with the GitHub account and repository name:

```cmd
git clone https://github.com/ACCOUNT/REPOSITORY.git
cd REPOSITORY\backend
```

The repository URL is not embedded in this README; use the **Code** button on the repository page to copy its HTTPS URL.

## Local setup

You need Python 3.12 and access to a MongoDB database, either a local MongoDB server or MongoDB Atlas.

From the `backend` directory, create and activate a virtual environment, install dependencies, and copy the sample environment file:

```cmd
py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and set `MONGO_URI` to your database connection string. For example, a local MongoDB URI is:

```dotenv
MONGO_URI=mongodb://localhost:27017
```

For Atlas, use the connection string provided by Atlas and replace its username, password, and database placeholders. Ensure your network/IP access rules allow connections from your development machine. Keep `.env` private and never commit real credentials.

## Environment variables

The `.env.example` file lists all supported settings.

| Variable | Required for | Description |
| --- | --- | --- |
| `MONGO_URI` | Starting the API | MongoDB connection string. |
| `MONGODB_DATABASE` | Optional | Database name; defaults to `pillars_fc`. |
| `FRONTEND_ORIGIN` | Optional | Frontend origin allowed by CORS and used in member verification links; defaults to `http://localhost:3000`. Set it to the frontend's exact origin when it differs. |
| `ADMIN_USERNAME` | Admin sign-in | Admin account username. |
| `ADMIN_PASSWORD_HASH` | Admin sign-in | Argon2 password hash, not the plain-text password. |
| `ADMIN_SESSION_SECRET` | Admin sign-in | Random signing secret of at least 32 characters. |
| `ADMIN_SESSION_COOKIE_SECURE` | Production admin sign-in | Set to `false` for local HTTP; use `true` over HTTPS in production. |
| `ADMIN_SESSION_COOKIE_SAMESITE` | Session cookies | Cookie policy: `lax`, `strict`, or `none`. Defaults to `lax`. |
| `ADMIN_SESSION_TTL_SECONDS` | Optional | Admin session lifetime; defaults to 28,800 seconds. |
| `MEMBER_SESSION_SECRET` | Member sign-in | A separate random signing secret of at least 32 characters. |
| `MEMBER_SESSION_TTL_SECONDS` | Optional | Member session lifetime; defaults to 28,800 seconds. |
| `RESEND_API_KEY` | Contact form and member activation email | Resend API key. |
| `MAIL_FROM_RESEND` | Contact form and member activation email | Verified sender address/name configured with Resend. |
| `MAIL_USERNAME` | Contact form | Destination email address for website contact messages. |
| `CLOUDINARY_CLOUD_NAME` | Image uploads | Cloudinary cloud name. |
| `CLOUDINARY_API_KEY` | Image uploads | Cloudinary API key. |
| `CLOUDINARY_API_SECRET` | Image uploads | Cloudinary API secret. Never put this in frontend configuration. |

Settings for email, images, admin, and member sessions are optional for running public API features, but the corresponding feature will report that it is unavailable until configured. Configure all three Cloudinary values to enable image uploads, and configure both Resend values to enable member activation emails.

Generate an Argon2 hash for the admin password:

```cmd
python -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass('Admin password: ')))"
```

Generate separate signing secrets for admin and member sessions:

```cmd
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated hash and secrets in `.env`; do not store the plain-text admin password there.

## Run locally

With the virtual environment activated and `.env` configured, start the API from the `backend` directory:

```cmd
python -m uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. MongoDB must be reachable when the API starts; startup checks the connection and creates the required indexes.

## API documentation

With the local server running:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>
- Health check: <http://127.0.0.1:8000/api/v1/health/>

Use Swagger's **Try it out** controls to explore and call the API. Admin and member endpoints require their respective configured account/session.

## Main API features

All versioned routes use the `/api/v1` prefix.

- **Members:** public directory and member details; public membership applications; admin member management, annual registrations, and application review.
- **Admin authentication:** login, session check, and logout.
- **Member accounts:** account activation, email verification, login, session check, and logout.
- **Player of the Month:** public winner and poll information; authenticated member nominations and votes; admin round management.
- **News:** public published news list and article details; admin article publishing with Markdown content and an optional photo gallery.
- **Club information:** executives, daily quote, and football quiz.
- **Contact and event subscriptions:** contact messages are emailed through Resend; event subscription emails are stored in MongoDB.

See the OpenAPI documentation for request schemas, parameters, and response details for each endpoint.

## Tests

Install development dependencies, including Pytest and HTTPX:

```cmd
python -m pip install -r requirements-dev.txt
```

Run the backend tests from the `backend` directory:

```cmd
python -m pytest
```

Tests mock external email services and do not require a live Resend account or MongoDB instance.

## Lint and format

Check the Python code with Ruff:

```cmd
ruff check app tests
ruff format --check app tests
```

To apply Ruff's automatic fixes and formatting:

```cmd
ruff check --fix app tests
ruff format app tests
```

Ruff configuration is in `pyproject.toml`.
