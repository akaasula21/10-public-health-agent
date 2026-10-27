import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.data.bq_client import get_bq_client

def main():
    client = get_bq_client()
    project = "qwiklabs-gcp-03-c81d344a3430"
    sql = f"""
    CREATE OR REPLACE VIEW `{project}.a4i_health.bronx_tracts_2020` AS
    SELECT * FROM `{project}.a4i_health.v_clean_bronx_tracts`
    """
    print(f"Creating view {project}.a4i_health.bronx_tracts_2020...")
    client.query(sql).result()
    print("SUCCESS: View created!")

if __name__ == "__main__":
    main()
