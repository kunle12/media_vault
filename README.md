# MediaVault

A Flask-based personal multimedia management application that allows users to upload, view, and manage their video and audio collection.

## Features

- **Passwordless Authentication**: Email-based verification code login
- **Media Upload**: Upload media files (videos: mp4, avi, mov, mkv, wmv, flv, webm and audio: mp3, wav, ogg) up to 500MB
- **Media Management**: View, download, and delete your uploaded files
- **Dashboard**: Personal dashboard showing all your uploaded media
- **Security**: Time-sensitive verification codes (5 min), rate limiting, session-based auth

## Requirements

- Python 3.8+
- SQLite3

## Installation

1. Clone the repository and navigate to the project directory:
   ```bash
   cd MediaVault
   ```

2. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure allowed emails by setting the `ALLOWED_EMAILS` environment variable (whitespace-separated emails):
   ```
   export ALLOWED_EMAILS="user@example.com admin@example.com your-email@domain.com"
   ```

5. (Optional) Create an `.env` file to override defaults:
   ```env
   SECRET_KEY=your_secret_key_here
   UPLOAD_FOLDER=uploads
   DATABASE=videodb.sqlite
   ```

6. (Optional) Configure email sending:
   ```env
   # Email provider: generic, aws_ses
   EMAIL_PROVIDER=aws_ses
   
   # AWS SES (if using AWS SES)
   AWS_REGION=us-east-1
   SMTP_USER=AKIxxxxxxxxxxxx
   SMTP_PASSWORD=BPxxxxxxxxxxxxxxxxxxxxx
   FROM_EMAIL=noreply@yourdomain.com
   
   # Or Gmail/Other SMTP
   # SMTP_HOST=smtp.gmail.com
   # SMTP_PORT=587
   # SMTP_USER=your@gmail.com
   # SMTP_PASSWORD=your_app_password
   ```

7. Run the application - database and upload folder are created automatically:
   ```bash
   python app.py
   ```

## Running the Application

```bash
python app.py
```

The application will start on `http://localhost:5050`. The database and uploads folder are created automatically on first run.

## Authentication

MediaVault uses **passwordless email authentication**:

1. Enter your email on the sign-in modal
2. If your email is in the allowed list, a 6-character verification code is sent
3. Enter the code (valid for 5 minutes, 5 retry attempts max)
4. Session is created and you can access the dashboard

### Allowed Emails

Set the `ALLOWED_EMAILS` environment variable with whitespace-separated email addresses to control who can access the application.

### Email Configuration

The app supports multiple email providers:

| Provider | Setup |
|----------|-------|
| **Debug (default)** | No config needed - codes printed to console |
| **AWS SES** | Set `EMAIL_PROVIDER=aws_ses`, `AWS_REGION`, SMTP credentials |
| **Gmail** | Set `SMTP_HOST=smtp.gmail.com`, use App Password |
| **Other SMTP** | Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` |

## Project Structure

```
MediaVault/
├── app.py                   # Main application file
├── auth.py                  # Authentication blueprint
├── requirements.txt         # Python dependencies
├── README.md                # Documentation
├── Dockerfile               # Docker configuration
├── docker-compose.yml       # Docker Compose configuration
├── videodb.sqlite          # SQLite database (auto-created)
├── templates/              # HTML templates
│   ├── layout.html         # Base template
│   ├── index.html          # Home page
│   ├── dashboard.html      # User dashboard
│   ├── upload.html         # Media upload page
│   ├── video.html          # Media view page
│   ├── auth_modals.html    # Authentication modals
│   └── auth_trigger.html   # Auth trigger page
└── uploads/                # Media storage directory (auto-created)
```

## Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Home page |
| `/auth/request-code` | POST | Request verification code |
| `/auth/verify-code` | POST | Verify code and login |
| `/auth/logout` | POST | User logout |
| `/auth/status` | GET | Check auth status |
| `/dashboard` | GET | User dashboard (protected) |
| `/upload` | GET, POST | Media upload (protected) |
| `/video/<id>` | GET | View media (protected) |
| `/video/<id>/download` | GET | Download media (protected) |
| `/video/<id>/delete` | POST | Delete media (protected) |

## Database Schema

### users
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| email | TEXT | Unique email |
| created_at | TIMESTAMP | First login timestamp |

### videos
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| filename | TEXT | Unique stored filename |
| original_filename | TEXT | Original file name |
| file_path | TEXT | Path to stored file |
| file_size | INTEGER | File size in bytes |
| uploaded_at | TIMESTAMP | Upload timestamp |
| user_id | INTEGER | Foreign key to users |

### Database Indexes
- `idx_videos_user_id` on `videos(user_id)`
- `idx_users_email` on `users(email)`

## Configuration

The following configuration options can be set via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| SECRET_KEY | random 32-byte hex | Flask secret key (auto-generated) |
| WTF_CSRF_ENABLED | True | Enable CSRF protection |
| UPLOAD_FOLDER | uploads | Directory for storing media |
| MAX_CONTENT_LENGTH | 524288000 (500MB) | Maximum upload size |
| DATABASE | videodb.sqlite | SQLite database file |
| CACHE_TYPE | simple | Cache type (simple, redis) |
| EMAIL_PROVIDER | generic | Email provider (generic, aws_ses) |

### Email/SMTP Configuration

| Variable | Description |
|----------|-------------|
| EMAIL_PROVIDER | Provider type: generic, aws_ses |
| AWS_REGION | AWS region for SES (e.g., us-east-1) |
| SMTP_HOST | SMTP server hostname |
| SMTP_PORT | SMTP server port (default: 587) |
| SMTP_USER | SMTP username |
| SMTP_PASSWORD | SMTP password |
| FROM_EMAIL | Sender email address |

## Allowed File Formats

### Video
- mp4
- avi
- mov
- mkv
- wmv
- flv
- webm

### Audio
- mp3
- wav
- ogg

## License

MIT License
