[33mcommit c0c7aa2e0a0a0f8920d0a7d5b677cecbd2439c46[m
Author: williamcjrogers <williamcjrogers@gmail.com>
Date:   Thu Dec 4 20:04:31 2025 +0000

    fix: PST processing import path and Redis SSL config
    
    - Fix worker import: /code -> /code/api for pst_processor module
    - Fix Redis SSL: CERT_REQUIRED -> required (valid parameter value)
    
    These fixes resolve:
    1. 'No module named app' error when processing PST files
    2. 'Invalid SSL Certificate Requirements Flag' cache warnings

 pst-analysis-engine/k8s-deployment.yaml  | 12 [32m++++++[m[31m------[m
 pst-analysis-engine/worker_app/worker.py |  3 [32m++[m[31m-[m
 2 files changed, 8 insertions(+), 7 deletions(-)
