import os
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .security import hash_password
import logging

logger = logging.getLogger(__name__)

# Database URL inside container
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://vericase:vericase@postgres:5432/vericase"
)


def reset_admin_password():
    # Avoid logging DATABASE_URL (it may contain credentials)
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        emails_raw = (
            os.getenv("ADMIN_EMAILS")
            or os.getenv("ADMIN_EMAIL")
            or "admin@veri-case.com,admin@vericase.com"
        )
        emails = [e.strip() for e in emails_raw.split(",") if e.strip()]

        # IMPORTANT:
        # - On container startup, we should NOT overwrite an existing admin user's
        #   password unless explicitly requested via ADMIN_RESET_FORCE=true.
        # - ADMIN_PASSWORD is only used for creating NEW admin users, or when
        #   ADMIN_RESET_FORCE=true to reset existing users.
        # - This prevents password resets on every pod restart/scale event.
        admin_password_env = os.getenv("ADMIN_PASSWORD")
        force_reset = str(os.getenv("ADMIN_RESET_FORCE", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        # Only reset existing users' passwords when explicitly forced
        should_reset_password = force_reset

        # NOTE: We intentionally do not log the plaintext password.
        new_password = admin_password_env or "ChangeMe123"
        # Always generate a hash - needed for creating new users even if not resetting existing
        new_hash = hash_password(new_password)

        show_password = str(os.getenv("ADMIN_PASSWORD_PRINT", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }

        logger.info(f"ADMIN_RESET_FORCE={os.getenv('ADMIN_RESET_FORCE', '(not set)')}")
        logger.info(f"should_reset_password={should_reset_password}")

        for email in emails:
            # Check if user exists
            result = session.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": email}
            )
            user = result.fetchone()

            if user:
                user_id = user[0]
                if should_reset_password:
                    logger.info(
                        f"Found user {email}. Resetting password and UNLOCKING..."
                    )
                    # Reset password, clear lockout fields, and ensure active/verified.
                    _ = session.execute(
                        text(
                            """
                            UPDATE users
                            SET password_hash = :new_hash,
                                failed_login_attempts = 0,
                                locked_until = NULL,
                                reset_token = NULL,
                                reset_token_expires = NULL,
                                is_active = TRUE,
                                email_verified = TRUE
                            WHERE email = :email
                            """
                        ),
                        {"new_hash": new_hash, "email": email},
                    )

                    # Revoke existing sessions so the new password takes effect immediately.
                    _ = session.execute(
                        text("DELETE FROM user_sessions WHERE user_id = :user_id"),
                        {"user_id": user_id},
                    )
                else:
                    logger.info(
                        f"Found user {email}. Unlocking/activating (password unchanged)."
                    )
                    _ = session.execute(
                        text(
                            """
                            UPDATE users
                            SET failed_login_attempts = 0,
                                locked_until = NULL,
                                reset_token = NULL,
                                reset_token_expires = NULL,
                                is_active = TRUE,
                                email_verified = TRUE
                            WHERE email = :email
                            """
                        ),
                        {"email": email},
                    )

                session.commit()
                logger.info(
                    f"✅ Admin updated: {email}{' (sessions revoked)' if should_reset_password else ''}"
                )
            else:
                logger.warning(f"User {email} not found. Creating it...")
                # Create admin user.
                user_id = str(uuid.uuid4())
                _ = session.execute(
                    text(
                        """
                        INSERT INTO users (
                            id,
                            email,
                            password_hash,
                            role,
                            failed_login_attempts,
                            is_active,
                            email_verified
                        )
                        VALUES (
                            :id,
                            :email,
                            :hash,
                            'ADMIN',
                            0,
                            TRUE,
                            TRUE
                        )
                        """
                    ),
                    {"id": user_id, "email": email, "hash": new_hash},
                )
                session.commit()
                logger.info(f"✅ Admin created: {email}")

        if show_password and should_reset_password:
            # Explicit opt-in only.
            print(f"ADMIN_PASSWORD={new_password}")

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    reset_admin_password()
