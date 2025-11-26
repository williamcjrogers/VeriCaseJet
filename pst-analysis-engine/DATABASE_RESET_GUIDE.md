# Database Reset Guide

## What Was Done

The database has been completely wiped clean, including:

1. ✅ **SQLite Database** - `vericase.db` file deleted
2. ✅ **Upload Directory** - All uploaded files cleared from `uploads/`
3. ✅ **Data Directory** - All data files cleared from `data/`

## Current State

- **Database**: Fresh start (no tables, no data)
- **Uploaded Files**: All removed
- **User Accounts**: None (will need to create admin)

## Next Steps to Get Running

### 1. Start the Server

The database schema will be automatically created when you start the API server:

```powershell
cd api
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or use the provided start script:

```powershell
cd pst-analysis-engine
.\start.sh
```

### 2. Create Admin User

After the server is running, create the default admin user:

```powershell
cd api
python create_admin.py
```

This will create a default admin account. Check the script output for credentials.

### 3. (Optional) Run Migrations

If you need to manually run database migrations:

```powershell
cd api
python apply_migrations.py
```

## Future Database Resets

### Using the Reset Scripts

I've created two scripts for future database resets:

#### PowerShell (Windows)
```powershell
cd pst-analysis-engine
.\reset-database.ps1
```

#### Bash (Linux/Mac)
```bash
cd pst-analysis-engine
chmod +x reset-database.sh
./reset-database.sh
```

Both scripts will:
1. Ask for confirmation (type "YES" to proceed)
2. Delete the database file
3. Clean upload directories
4. Recreate the database schema
5. Create the default admin user

### Manual Reset (Alternative)

If you prefer to do it manually:

```powershell
# 1. Delete database
Remove-Item vericase.db -Force

# 2. Clean uploads (optional)
Remove-Item uploads/* -Recurse -Force
Remove-Item data/* -Recurse -Force

# 3. Restart server (database auto-created)
cd api
uvicorn app.main:app --reload

# 4. Create admin
python create_admin.py
```

## PostgreSQL Databases

If you're using PostgreSQL instead of SQLite:

1. The reset scripts will automatically detect and clean PostgreSQL databases
2. Ensure your `DATABASE_URL` environment variable is set correctly
3. The scripts use `psycopg2` to drop all tables and recreate them

## Troubleshooting

### Database File Still Exists
If `vericase.db` wasn't deleted, you may have file locks. Stop all running processes:
- Stop the API server
- Stop any worker processes
- Close any database browser tools
- Then try again

### Permission Errors
Run PowerShell or terminal as Administrator if you get permission errors.

### Schema Issues
If tables aren't being created properly:
1. Check that migration files exist in `api/migrations/`
2. Verify your `DATABASE_URL` is set correctly
3. Run migrations manually: `python api/apply_migrations.py`

## What Gets Preserved

The following are **NOT** deleted during reset:
- Migration files in `api/migrations/`
- Configuration files (`.env`, `configs/`)
- Documentation
- Source code

## Database Location

- **SQLite**: `pst-analysis-engine/vericase.db`
- **PostgreSQL**: As configured in your `DATABASE_URL` environment variable

## Default Credentials

After reset, the default admin credentials are typically:
- **Email**: admin@vericase.local
- **Password**: Check the output of `create_admin.py`

⚠️ **IMPORTANT**: Change these credentials immediately after first login!

## Notes

- Always backup important data before resetting
- Consider exporting data if you need to preserve anything
- The reset is irreversible
- Perfect for development/testing when you want a clean slate


