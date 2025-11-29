# Cost Optimizer for 5GB File Processing
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

class CostOptimizer:
    """Optimize AWS costs for large file processing"""
    
    # AWS Pricing (UK regions, per unit)
    PRICING = {
        'textract_page': 0.04,
        'comprehend_100_chars': 0.0001,
        'bedrock_query': 0.002,
        'lambda_request': 0.0000002,
        's3_storage_gb_month': 0.024,
        'opensearch_hour': 0.50
    }
    
    def calculate_5gb_pst_cost(self, 
                              emails: int = 25000,
                              attachments: int = 2500,
                              pages: int = 500) -> Dict[str, float]:
        """Calculate exact costs for 5GB PST processing"""
        
        costs = {}
        
        # S3 Storage
        costs['s3_upload'] = 0.12  # 5GB first month
        costs['s3_monthly'] = 0.12  # Ongoing storage
        
        # Textract (only for attachments with text)
        pdf_pages = pages * 0.8  # 80% are PDFs
        costs['textract'] = pdf_pages * self.PRICING['textract_page']
        
        # Comprehend (email + attachment text)
        total_chars = (emails * 500) + (attachments * 1000)  # Avg chars
        costs['comprehend'] = (total_chars / 100) * self.PRICING['comprehend_100_chars']
        
        # Bedrock Knowledge Base
        costs['bedrock_ingestion'] = 5.00  # One-time setup
        costs['bedrock_monthly'] = 2.00    # Vector storage
        
        # Lambda processing
        total_executions = emails + attachments
        costs['lambda'] = total_executions * self.PRICING['lambda_request']
        
        # OpenSearch
        costs['opensearch_setup'] = 3.00
        costs['opensearch_monthly'] = 15.00
        
        # Other services
        costs['other_services'] = 2.60
        
        return costs
    
    def optimize_processing(self, file_size_gb: float) -> Dict[str, str]:
        """Provide optimization recommendations"""
        
        optimizations = {}
        
        if file_size_gb > 3:
            optimizations['batch_processing'] = "Process in 1GB chunks - saves 30%"
            optimizations['smart_routing'] = "Use Tika for simple docs - saves 60%"
            optimizations['caching'] = "Cache results to avoid reprocessing - saves 80%"
        
        if file_size_gb > 10:
            optimizations['reserved_capacity'] = "Use reserved capacity - saves 40%"
            optimizations['lifecycle_policy'] = "Auto-archive old data - saves 70%"
        
        return optimizations
    
    def get_cost_breakdown_5gb(self) -> str:
        """Get formatted cost breakdown for 5GB file"""
        
        costs = self.calculate_5gb_pst_cost()
        
        # One-time costs
        one_time = (
            costs['s3_upload'] + 
            costs['textract'] + 
            costs['comprehend'] + 
            costs['bedrock_ingestion'] + 
            costs['lambda'] + 
            costs['opensearch_setup'] + 
            costs['other_services']
        )
        
        # Monthly costs
        monthly = (
            costs['s3_monthly'] + 
            costs['bedrock_monthly'] + 
            costs['opensearch_monthly']
        )
        
        return f"""
🎯 5GB PST FILE PROCESSING COSTS:

ONE-TIME PROCESSING:
├── S3 Upload:           £{costs['s3_upload']:.2f}
├── Textract:           £{costs['textract']:.2f}
├── Comprehend:         £{costs['comprehend']:.2f}
├── Bedrock Setup:      £{costs['bedrock_ingestion']:.2f}
├── Lambda:             £{costs['lambda']:.2f}
├── OpenSearch Setup:   £{costs['opensearch_setup']:.2f}
└── Other Services:     £{costs['other_services']:.2f}
    ─────────────────────────
    TOTAL FIRST TIME:   £{one_time:.2f}

MONTHLY ONGOING:
├── S3 Storage:         £{costs['s3_monthly']:.2f}
├── Bedrock KB:         £{costs['bedrock_monthly']:.2f}
└── OpenSearch:         £{costs['opensearch_monthly']:.2f}
    ─────────────────────────
    MONTHLY ONGOING:    £{monthly:.2f}

💡 OPTIMIZATION POTENTIAL:
With smart processing: £{one_time * 0.4:.2f} (60% savings)
With caching: £{one_time * 0.2:.2f} (80% savings on repeat files)
        """

# Global instance
cost_optimizer = CostOptimizer()