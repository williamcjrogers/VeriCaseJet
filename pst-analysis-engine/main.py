from flask import Flask, jsonify, render_template, request
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Security configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32))
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent XSS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection

# Determine environment
ENV = os.environ.get('FLASK_ENV', 'production')
DEBUG = ENV == 'development'

if not DEBUG and app.config['SECRET_KEY'] == os.urandom(32):
    logger.warning("SECRET_KEY not set in production - using random key (sessions won't persist)")


@app.after_request
def set_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    return response


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    logger.warning("404 error: %s", request.path)
    return jsonify({"error": "Resource not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error("500 error: %s", str(error), exc_info=True)
    return jsonify({"error": "Internal server error"}), 500


@app.route("/", methods=["GET"])
def index():
    """Render main page"""
    try:
        return render_template("index.html")
    except Exception as e:
        logger.error("Error rendering index: %s", str(e), exc_info=True)
        return jsonify({"error": "Failed to load page"}), 500


@app.route("/languages", methods=["GET"])
def get_languages():
    """Get list of programming languages"""
    try:
        languages = [
            {"id": 1, "name": "Python"},
            {"id": 2, "name": "JavaScript"},
            {"id": 3, "name": "Java"},
            {"id": 4, "name": "C#"},
            {"id": 5, "name": "C++"},
        ]
        return jsonify(languages)
    except Exception as e:
        logger.error("Error fetching languages: %s", str(e), exc_info=True)
        return jsonify({"error": "Failed to fetch languages"}), 500


if __name__ == "__main__":
    # Never run with debug=True in production
    if DEBUG:
        logger.info("Starting Flask app in DEVELOPMENT mode")
        app.run(debug=True, host='127.0.0.1', port=5000)
    else:
        logger.info("Starting Flask app in PRODUCTION mode")
        # In production, use a proper WSGI server like gunicorn
        app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))


