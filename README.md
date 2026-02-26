# VideoVault

A Flask-based personal video management application that allows users to upload, view, and manage their video collection.

## Features

- **User Authentication**: Register and login with email/password or Google OAuth
- **Video Upload**: Upload video files (mp4, avi, mov, mkv, wmv, flv, webm) up to 500MB
- **Video Management**: View, download, and delete your uploaded videos
- **Dashboard**: Personal dashboard showing all your uploaded videos
- **Security**: Password hashing with bcrypt, session-based authentication, CSRF protection

## Requirements

- Python 3.8+
- SQLite3

## Installation

1. Clone the repository and navigate to the project directory:
   ```bash
   cd VideoVault
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

4. (Optional) Create an `.env` file to override defaults:
   ```env
   SECRET_KEY=your_secret_key_here
   UPLOAD_FOLDER=uploads
   DATABASE=videodb.sqlite
   GOOGLE_CLIENT_ID=your_google_client_id
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   ```

5. Run the application - database and upload folder are created automatically:
   ```bash
   python app.py
   ```

## Running the Application

```bash
python app.py
```

The application will start on `http://localhost:5050`. The database and uploads folder are created automatically on first run.

## Project Structure

```
VideoVault/
├── app.py              # Main application file
├── requirements.txt    # Python dependencies
├── README.md           # Documentation
├── videodb.sqlite     # SQLite database (auto-created)
├── templates/         # HTML templates
│   ├── layout.html    # Base template
│   ├── index.html     # Home page
│   ├── register.html  # Registration page
│   ├── login.html     # Login page
│   ├── dashboard.html # User dashboard
│   ├── upload.html    # Video upload page
│   └── video.html     # Video view page
└── uploads/           # Video storage directory (auto-created)
```

## Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Home page |
| `/register` | GET, POST | User registration |
| `/login` | GET, POST | User login |
| `/login/google` | GET | Google OAuth login |
| `/login/google/callback` | GET | Google OAuth callback |
| `/logout` | GET | User logout |
| `/dashboard` | GET | User dashboard (protected) |
| `/upload` | GET, POST | Video upload (protected) |
| `/video/<id>` | GET | View video (protected) |
| `/video/<id>/download` | GET | Download video (protected) |
| `/video/<id>/delete` | POST | Delete video (protected) |

## Database Schema

### users
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| username | TEXT | Unique username |
| email | TEXT | Unique email |
| password_hash | TEXT | Hashed password |
| google_id | TEXT | Google OAuth ID |
| created_at | TIMESTAMP | Registration timestamp |

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
- `idx_users_google_id` on `users(google_id)`

## Configuration

The following configuration options can be set via environment variables or in app.py:

| Variable | Default | Description |
|----------|---------|-------------|
| SECRET_KEY | random 32-byte hex | Flask secret key (auto-generated) |
| WTF_CSRF_ENABLED | True | Enable CSRF protection |
| UPLOAD_FOLDER | uploads | Directory for storing videos |
| MAX_CONTENT_LENGTH | 524288000 (500MB) | Maximum upload size |
| DATABASE | videodb.sqlite | SQLite database file |
| GOOGLE_CLIENT_ID | - | Google OAuth client ID |
| GOOGLE_CLIENT_SECRET | - | Google OAuth client secret |

## Allowed Video Formats

- mp4
- avi
- mov
- mkv
- wmv
- flv
- webm

## License

MIT License
