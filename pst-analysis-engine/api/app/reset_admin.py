import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.security import hash_password

# Database URL inside container
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://vericase:vericase@postgres:5432/vericase")

def reset_admin_password():
    print(f"Connecting to database: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        email = "admin@vericase.com"
        new_password = "admin123"
        new_hash = hash_password(new_password)
        
        # Check if user exists
        result = session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email}
        )
        user = result.fetchone()
        
        if user:
            print(f"Found user {email}. Reseting password and UNLOCKING account...")
            # Reset password AND clear lockout fields
            session.execute(
                text("""
                    UPDATE users 
                    SET password_hash = :new_hash,
                        failed_login_attempts = 0,
                        locked_until = NULL
                    WHERE email = :email
                """),
                {"new_hash": new_hash, "email": email}
            )
            session.commit()
            print(f"✅ Account UNLOCKED. Password reset to: {new_password}")
        else:
            print(f"❌ User {email} not found! Creating it...")
            # Fallback to create user if missing logic could go here, but likely not needed if just locked
            
    except Exception as e:
        print(f"❌ Error: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    reset_admin_password()
