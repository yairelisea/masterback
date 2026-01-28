import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL not found in .env file.")
    exit(1)

# Normalize for SQLAlchemy to use psycopg (v3)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

def deep_search():
    try:
        engine = create_engine(DATABASE_URL)
        keywords = ["erasmo", "erasmo gonzales"]
        k1 = f"%{keywords[0]}%"
        k2 = f"%{keywords[1]}%"
        
        with engine.connect() as conn:
            print(f"--- Database Status ---")
            tables = ["raw_scrape_data", "ingested_items", "analytic_results", "analyses", "campaigns"]
            for table in tables:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"Table {table:20}: {count} records")
            
            print(f"\n--- Searching for: {keywords} ---\n")

            # 1. raw_scrape_data (text and metadata)
            print("Searching in 'raw_scrape_data'...")
            query_raw = text("""
                SELECT id, platform, "postUrl", "createdAt"
                FROM raw_scrape_data
                WHERE "rawText" ILIKE :k1 OR "rawText" ILIKE :k2
                   OR CAST("metadataJson" AS TEXT) ILIKE :k1
                   OR CAST("metadataJson" AS TEXT) ILIKE :k2
            """)
            res_raw = conn.execute(query_raw, {"k1": k1, "k2": k2}).fetchall()
            print(f"Found {len(res_raw)} records in raw_scrape_data")

            # 2. ingested_items
            print("Searching in 'ingested_items'...")
            query_items = text("""
                SELECT id, title, url, "createdAt"
                FROM ingested_items
                WHERE title ILIKE :k1 OR title ILIKE :k2
            """)
            res_items = conn.execute(query_items, {"k1": k1, "k2": k2}).fetchall()
            print(f"Found {len(res_items)} records in ingested_items")

            # 3. analytic_results
            print("Searching in 'analytic_results'...")
            query_analytic = text("""
                SELECT id, "postAuthor", "postUrl", "createdAt"
                FROM analytic_results
                WHERE "postContent" ILIKE :k1 OR "postContent" ILIKE :k2
                   OR narrative ILIKE :k1 OR narrative ILIKE :k2
                   OR summary ILIKE :k1 OR summary ILIKE :k2
            """)
            res_analytic = conn.execute(query_analytic, {"k1": k1, "k2": k2}).fetchall()
            print(f"Found {len(res_analytic)} records in analytic_results")

            # 4. analyses (Legacy analyses table)
            print("Searching in 'analyses'...")
            query_analyses = text("""
                SELECT id, summary, "createdAt"
                FROM analyses
                WHERE summary ILIKE :k1 OR summary ILIKE :k2
            """)
            res_analyses = conn.execute(query_analyses, {"k1": k1, "k2": k2}).fetchall()
            print(f"Found {len(res_analyses)} records in analyses")

            print("\n" + "="*50)
            print("SUMMARY OF MATCHES")
            print("="*50)
            
            if res_raw:
                print(f"\nRAW SCRAPE DATA ({len(res_raw)}):")
                for r in res_raw[:10]: # Limit output
                    print(f" - [{r.platform}] {r.postUrl}")
            
            if res_items:
                print(f"\nINGESTED ITEMS ({len(res_items)}):")
                for r in res_items[:10]:
                    print(f" - {r.title[:100]}... ({r.url})")
            
            if res_analytic:
                print(f"\nANALYTIC RESULTS ({len(res_analytic)}):")
                for r in res_analytic[:10]:
                    print(f" - By: {r.postAuthor} | {r.postUrl}")
            
            if res_analyses:
                print(f"\nLEGACY ANALYSES ({len(res_analyses)}):")
                for r in res_analyses[:10]:
                    print(f" - {r.summary[:100]}...")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    deep_search()
