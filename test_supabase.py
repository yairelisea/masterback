
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
import getpass
import sys

async def check_connection():
    """Tests connection to Supabase DB."""
    try:
        host = "db.hhvffufgxkvtpzfizwnb.supabase.co"
        user = "postgres"
        db_name = "postgres"
        # Supabase offers two ports: 5432 for direct connection 
        # and 6543 for the transaction-based connection pooler.
        port = 6543 
        
        # Securely prompt for password
        password = getpass.getpass(f"Please enter password for user '{user}' on host '{host}': ")
        
        db_url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db_name}"
        
        print(f"\nAttempting to connect to {host}:{port}...")
        engine = create_async_engine(db_url)
        
        async with engine.connect() as connection:
            print("✅ Connection successful!")
            
    except Exception as e:
        print(f"❌ Connection failed: {e}", file=sys.stderr)
        print("\nTroubleshooting suggestions:", file=sys.stderr)
        print("1. Verify your password is correct.", file=sys.stderr)
        print("2. Check if your computer's IP is added to the Network Restrictions in your Supabase project settings.", file=sys.stderr)
        print("3. Try changing the 'port' in the script to 6543 (the connection pooler port).", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(check_connection())
