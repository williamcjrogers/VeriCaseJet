## Simple Flask Languages API

This minimal Flask app exposes one JSON endpoint and a tiny HTML page with enterprise-grade security.

- **API**: `GET /languages` → returns a JSON array of programming languages
- **UI**: `GET /` → loads a basic page that fetches and displays the languages

### Security Features ✅

- **Security Headers**: XSS protection, clickjacking prevention, HSTS, CSP
- **Secure Sessions**: HTTPOnly, Secure, SameSite cookies
- **Environment-Based Config**: Automatic dev/production mode detection
- **Structured Logging**: Comprehensive request/error logging
- **Error Handling**: Safe error responses (no stack trace leakage)

### Setup

1. (Optional) Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Set environment variables (production):

   ```bash
   export FLASK_ENV=production
   export SECRET_KEY=your-secret-key-here
   export PORT=8080
   ```

### Run

**Development:**
```bash
export FLASK_ENV=development
python main.py
```

**Production (with gunicorn):**
```bash
export FLASK_ENV=production
export SECRET_KEY=your-secret-key
gunicorn -w 4 -b 0.0.0.0:8080 main:app
```

Open:

- UI: http://127.0.0.1:5000/ (dev) or https://your-domain.com (prod)
- API: http://127.0.0.1:5000/languages (dev) or https://your-domain.com/languages (prod)

# PST Analysis Engine

## Overview
The PST Analysis Engine is a powerful tool designed for processing and analyzing PST files. It extracts data, processes emails, and facilitates migration to various formats and storage systems.

## Project Structure
```
pst-analysis-engine
├── src
│   ├── __main__.py
│   ├── core
│   │   ├── pst_reader.py
│   │   ├── pst_parser.py
│   │   └── email_processor.py
│   ├── migration
│   │   ├── migration_engine.py
│   │   └── adapters
│   │       ├── exchange_adapter.py
│   │       └── imap_adapter.py
│   ├── processing
│   │   ├── attachment_extractor.py
│   │   ├── metadata_extractor.py
│   │   └── content_analyzer.py
│   ├── storage
│   │   ├── storage_manager.py
│   │   └── sqlite_backend.py
│   └── utils
│       ├── logger.py
│       └── validators.py
├── tests
│   ├── unit
│   │   ├── test_pst_reader.py
│   │   └── test_email_processor.py
│   └── integration
│       └── test_migration_flow.py
├── configs
│   └── default.yaml
├── pyproject.toml
├── requirements.txt
├── setup.cfg
├── LICENSE
└── README.md
```

## Installation
1. Clone the repository:
   ```
   git clone <repository-url>
   ```
2. Navigate to the project directory:
   ```
   cd pst-analysis-engine
   ```
3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage
To run the analysis engine, execute the following command:
```
python -m src
```

## Security

This project follows security best practices. See [SECURITY_IMPROVEMENTS.md](SECURITY_IMPROVEMENTS.md) for details on implemented security measures.

**Key Security Features:**
- SQL injection prevention (parameterized queries)
- XSS protection (output encoding, CSP headers)
- CSRF protection (SameSite cookies)
- Log injection prevention (sanitized logging)
- Timezone-aware datetime handling
- Secure session management
- HTTPS enforcement in production

**Report Security Issues:**
Please report security vulnerabilities privately to the maintainers.

## Contributing
Contributions are welcome! Please submit a pull request or open an issue for any enhancements or bug fixes.

**Security Contributions:**
- Review [SECURITY_IMPROVEMENTS.md](SECURITY_IMPROVEMENTS.md) before submitting
- Follow secure coding practices
- Add tests for security-sensitive code
- Document security considerations

## License
This project is licensed under the MIT License. See the LICENSE file for details.