# AWS Lambda Functions for VeriCase Processing Pipeline
import json
import boto3
import logging
from typing import Dict, Any
import os

# Lambda function configurations
LAMBDA_FUNCTIONS = {
    'textract_processor': {
        'name': 'vericase-textract-processor',
        'runtime': 'python3.11',
        'handler': 'lambda_function.textract_handler',
        'timeout': 900,  # 15 minutes
        'memory': 1024
    },
    'comprehend_analyzer': {
        'name': 'vericase-comprehend-analyzer',
        'runtime': 'python3.11',
        'handler': 'lambda_function.comprehend_handler',
        'timeout': 300,  # 5 minutes
        'memory': 512
    },
    'document_classifier': {
        'name': 'vericase-document-classifier',
        'runtime': 'python3.11',
        'handler': 'lambda_function.classifier_handler',
        'timeout': 300,
        'memory': 512
    },
    'database_updater': {
        'name': 'vericase-database-updater',
        'runtime': 'python3.11',
        'handler': 'lambda_function.database_handler',
        'timeout': 300,
        'memory': 256
    },
    'knowledge_base_ingester': {
        'name': 'vericase-kb-ingester',
        'runtime': 'python3.11',
        'handler': 'lambda_function.kb_handler',
        'timeout': 600,
        'memory': 512
    },
    'analytics_processor': {
        'name': 'vericase-analytics-processor',
        'runtime': 'python3.11',
        'handler': 'lambda_function.analytics_handler',
        'timeout': 300,
        'memory': 512
    }
}

# Lambda Function Code Templates

TEXTRACT_PROCESSOR_CODE = '''
import json
import boto3
import logging
from typing import Dict, Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

textract = boto3.client('textract')

def textract_handler(event, context):
    """Process documents with Textract"""
    try:
        s3_bucket = event['s3_bucket']
        s3_key = event['s3_key']
        evidence_id = event['evidence_id']
        
        logger.info(f"Processing document: {s3_bucket}/{s3_key}")
        
        # Start document analysis
        response = textract.start_document_analysis(
            DocumentLocation={
                'S3Object': {'Bucket': s3_bucket, 'Name': s3_key}
            },
            FeatureTypes=['TABLES', 'FORMS', 'QUERIES', 'SIGNATURES'],
            QueriesConfig={
                'Queries': [
                    {'Text': 'What is the contract value?'},
                    {'Text': 'What is the completion date?'},
                    {'Text': 'Who are the parties to this contract?'},
                    {'Text': 'What is the project name?'},
                    {'Text': 'Are there any delay clauses?'},
                    {'Text': 'What are the payment terms?'}
                ]
            }
        )
        
        job_id = response['JobId']
        
        # Poll for completion (simplified for Lambda)
        import time
        max_attempts = 60  # 5 minutes max
        attempt = 0
        
        while attempt < max_attempts:
            result = textract.get_document_analysis(JobId=job_id)
            status = result['JobStatus']
            
            if status == 'SUCCEEDED':
                # Process results
                extracted_data = process_textract_results(result)
                
                return {
                    'statusCode': 200,
                    'body': {
                        'evidence_id': evidence_id,
                        'textract_data': extracted_data,
                        'job_id': job_id
                    }
                }
            elif status == 'FAILED':
                logger.error(f"Textract failed: {result.get('StatusMessage')}")
                return {
                    'statusCode': 500,
                    'body': {'error': 'Textract processing failed'}
                }
            
            time.sleep(5)
            attempt += 1
        
        # Timeout
        return {
            'statusCode': 408,
            'body': {'error': 'Textract processing timeout'}
        }
        
    except Exception as e:
        logger.error(f"Textract handler error: {e}")
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }

def process_textract_results(result: Dict) -> Dict[str, Any]:
    """Process Textract results into structured data"""
    extracted_data = {
        'text': '',
        'tables': [],
        'forms': {},
        'queries': {},
        'signatures': []
    }
    
    for block in result.get('Blocks', []):
        if block['BlockType'] == 'LINE':
            extracted_data['text'] += block.get('Text', '') + '\\n'
        elif block['BlockType'] == 'QUERY_RESULT':
            query_text = block.get('Text', '')
            query_alias = block.get('Query', {}).get('Alias', '')
            extracted_data['queries'][query_alias or 'query'] = query_text
    
    return extracted_data
'''

COMPREHEND_ANALYZER_CODE = '''
import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

comprehend = boto3.client('comprehend')

def comprehend_handler(event, context):
    """Analyze text with Comprehend"""
    try:
        text = event['textract_data']['text'][:5000]  # Truncate for API limits
        evidence_id = event['evidence_id']
        
        logger.info(f"Analyzing text for evidence: {evidence_id}")
        
        # Entity detection
        entities_response = comprehend.detect_entities(
            Text=text,
            LanguageCode='en'
        )
        
        # Sentiment analysis
        sentiment_response = comprehend.detect_sentiment(
            Text=text,
            LanguageCode='en'
        )
        
        # Key phrases
        phrases_response = comprehend.detect_key_phrases(
            Text=text,
            LanguageCode='en'
        )
        
        # PII detection
        pii_response = comprehend.detect_pii_entities(
            Text=text,
            LanguageCode='en'
        )
        
        analysis_result = {
            'entities': entities_response.get('Entities', []),
            'sentiment': sentiment_response.get('Sentiment'),
            'sentiment_scores': sentiment_response.get('SentimentScore', {}),
            'key_phrases': phrases_response.get('KeyPhrases', []),
            'pii_entities': pii_response.get('Entities', [])
        }
        
        return {
            'statusCode': 200,
            'body': {
                'evidence_id': evidence_id,
                'comprehend_analysis': analysis_result,
                'textract_data': event['textract_data']
            }
        }
        
    except Exception as e:
        logger.error(f"Comprehend handler error: {e}")
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }
'''

DOCUMENT_CLASSIFIER_CODE = '''
import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def classifier_handler(event, context):
    """Classify document type and generate tags"""
    try:
        textract_data = event['textract_data']
        comprehend_analysis = event['comprehend_analysis']
        evidence_id = event['evidence_id']
        
        logger.info(f"Classifying document: {evidence_id}")
        
        # Classify document type
        document_type = classify_document_type(textract_data, comprehend_analysis)
        confidence = calculate_classification_confidence(textract_data, comprehend_analysis)
        auto_tags = generate_auto_tags(textract_data, comprehend_analysis)
        
        # Extract structured data
        extracted_parties = [e['Text'] for e in comprehend_analysis['entities'] if e['Type'] == 'PERSON']
        extracted_dates = [e['Text'] for e in comprehend_analysis['entities'] if e['Type'] == 'DATE']
        extracted_amounts = [e['Text'] for e in comprehend_analysis['entities'] 
                           if e['Type'] in ['QUANTITY', 'OTHER'] and any(c in e['Text'] for c in ['£', '$', '€'])]
        
        classification_result = {
            'document_type': document_type,
            'confidence': confidence,
            'auto_tags': auto_tags,
            'extracted_parties': extracted_parties,
            'extracted_dates': extracted_dates,
            'extracted_amounts': extracted_amounts
        }
        
        return {
            'statusCode': 200,
            'body': {
                'evidence_id': evidence_id,
                'classification': classification_result,
                'textract_data': textract_data,
                'comprehend_analysis': comprehend_analysis
            }
        }
        
    except Exception as e:
        logger.error(f"Classifier handler error: {e}")
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }

def classify_document_type(textract_data, comprehend_analysis):
    """Classify document type based on content"""
    text = textract_data.get('text', '').lower()
    
    if any(word in text for word in ['contract', 'agreement', 'terms']):
        return 'contract'
    elif any(word in text for word in ['invoice', 'payment', 'amount due']):
        return 'invoice'
    elif any(word in text for word in ['drawing', 'plan', 'elevation']):
        return 'drawing'
    elif any(word in text for word in ['from:', 'to:', 'subject:']):
        return 'email'
    elif any(word in text for word in ['minutes', 'meeting', 'attendees']):
        return 'meeting_minutes'
    else:
        return 'other'

def calculate_classification_confidence(textract_data, comprehend_analysis):
    """Calculate confidence score"""
    confidence = 50
    if textract_data.get('tables'): confidence += 20
    if textract_data.get('forms'): confidence += 15
    if len(comprehend_analysis.get('entities', [])) > 5: confidence += 15
    return min(confidence, 100)

def generate_auto_tags(textract_data, comprehend_analysis):
    """Generate automatic tags"""
    tags = []
    text = textract_data.get('text', '').lower()
    
    construction_terms = {
        'delay': ['delay', 'behind schedule', 'late'],
        'variation': ['variation', 'change order'],
        'defect': ['defect', 'defective', 'fault'],
        'payment': ['payment', 'invoice', 'cost'],
        'safety': ['safety', 'accident', 'incident']
    }
    
    for tag, terms in construction_terms.items():
        if any(term in text for term in terms):
            tags.append(tag)
    
    return tags
'''

DATABASE_UPDATER_CODE = '''
import json
import boto3
import logging
import psycopg2
import os
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def database_handler(event, context):
    """Update database with processed evidence data"""
    try:
        evidence_id = event['evidence_id']
        textract_data = event['textract_data']
        comprehend_analysis = event['comprehend_analysis']
        classification = event['classification']
        
        logger.info(f"Updating database for evidence: {evidence_id}")
        
        # Connect to database
        conn = psycopg2.connect(
            host=os.environ['DB_HOST'],
            database=os.environ['DB_NAME'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD']
        )
        
        cur = conn.cursor()
        
        # Update evidence_items table
        update_query = """
        UPDATE evidence_items 
        SET 
            extracted_text = %s,
            extracted_metadata = %s,
            evidence_type = %s,
            classification_confidence = %s,
            auto_tags = %s,
            extracted_parties = %s,
            extracted_dates = %s,
            extracted_amounts = %s,
            processing_status = 'ready',
            ai_analyzed = true,
            processed_at = %s
        WHERE id = %s
        """
        
        enhanced_metadata = {
            'textract_data': textract_data,
            'comprehend_analysis': comprehend_analysis,
            'classification': classification,
            'processing_timestamp': datetime.utcnow().isoformat()
        }
        
        cur.execute(update_query, (
            textract_data.get('text', ''),
            json.dumps(enhanced_metadata),
            classification['document_type'],
            classification['confidence'],
            classification['auto_tags'],
            classification['extracted_parties'],
            classification['extracted_dates'],
            classification['extracted_amounts'],
            datetime.utcnow(),
            evidence_id
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Successfully updated evidence: {evidence_id}")
        
        return {
            'statusCode': 200,
            'body': {
                'evidence_id': evidence_id,
                'database_updated': True
            }
        }
        
    except Exception as e:
        logger.error(f"Database handler error: {e}")
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }
'''

KNOWLEDGE_BASE_INGESTER_CODE = '''
import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_agent = boto3.client('bedrock-agent-runtime')
s3 = boto3.client('s3')

def kb_handler(event, context):
    """Ingest processed evidence into Bedrock Knowledge Base"""
    try:
        evidence_id = event['evidence_id']
        textract_data = event['textract_data']
        classification = event['classification']
        
        logger.info(f"Ingesting evidence into KB: {evidence_id}")
        
        # Prepare document for knowledge base
        document_content = {
            'id': evidence_id,
            'content': textract_data.get('text', ''),
            'metadata': {
                'evidence_type': classification['document_type'],
                'confidence': classification['confidence'],
                'auto_tags': classification['auto_tags'],
                'extracted_parties': classification['extracted_parties'],
                'processing_date': event.get('processing_timestamp')
            }
        }
        
        # Upload to S3 in format expected by Bedrock KB
        kb_bucket = os.environ['KNOWLEDGE_BASE_BUCKET']
        kb_key = f"evidence/{evidence_id}.json"
        
        s3.put_object(
            Bucket=kb_bucket,
            Key=kb_key,
            Body=json.dumps(document_content),
            ContentType='application/json'
        )
        
        # Trigger knowledge base sync
        knowledge_base_id = os.environ['KNOWLEDGE_BASE_ID']
        data_source_id = os.environ['DATA_SOURCE_ID']
        
        sync_response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id
        )
        
        return {
            'statusCode': 200,
            'body': {
                'evidence_id': evidence_id,
                'kb_ingested': True,
                'sync_job_id': sync_response.get('ingestionJob', {}).get('ingestionJobId')
            }
        }
        
    except Exception as e:
        logger.error(f"KB ingester error: {e}")
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }
'''

ANALYTICS_PROCESSOR_CODE = '''
import json
import boto3
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

quicksight = boto3.client('quicksight')
eventbridge = boto3.client('events')

def analytics_handler(event, context):
    """Process analytics and trigger dashboard updates"""
    try:
        evidence_id = event['evidence_id']
        case_id = event.get('case_id')
        project_id = event.get('project_id')
        
        logger.info(f"Processing analytics for evidence: {evidence_id}")
        
        # Trigger analytics update event
        analytics_event = {
            'Source': 'vericase.analytics',
            'DetailType': 'Evidence Processed',
            'Detail': json.dumps({
                'evidence_id': evidence_id,
                'case_id': case_id,
                'project_id': project_id,
                'timestamp': datetime.utcnow().isoformat(),
                'event_type': 'evidence_processed'
            })
        }
        
        eventbridge.put_events(Entries=[analytics_event])
        
        # Trigger QuickSight dataset refresh if configured
        dataset_id = os.environ.get('QUICKSIGHT_DATASET_ID')
        if dataset_id:
            try:
                quicksight.create_ingestion(
                    DataSetId=dataset_id,
                    IngestionId=f"evidence-{evidence_id}-{int(datetime.utcnow().timestamp())}",
                    AwsAccountId=os.environ['AWS_ACCOUNT_ID']
                )
            except Exception as qs_error:
                logger.warning(f"QuickSight refresh failed: {qs_error}")
        
        return {
            'statusCode': 200,
            'body': {
                'evidence_id': evidence_id,
                'analytics_processed': True
            }
        }
        
    except Exception as e:
        logger.error(f"Analytics handler error: {e}")
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }
'''

# Lambda deployment helper
def create_lambda_deployment_package():
    """Create deployment packages for all Lambda functions"""
    lambda_codes = {
        'textract_processor': TEXTRACT_PROCESSOR_CODE,
        'comprehend_analyzer': COMPREHEND_ANALYZER_CODE,
        'document_classifier': DOCUMENT_CLASSIFIER_CODE,
        'database_updater': DATABASE_UPDATER_CODE,
        'knowledge_base_ingester': KNOWLEDGE_BASE_INGESTER_CODE,
        'analytics_processor': ANALYTICS_PROCESSOR_CODE
    }
    
    return lambda_codes

# Environment variables for Lambda functions
LAMBDA_ENV_VARS = {
    'DB_HOST': '${DATABASE_HOST}',
    'DB_NAME': '${DATABASE_NAME}',
    'DB_USER': '${DATABASE_USER}',
    'DB_PASSWORD': '${DATABASE_PASSWORD}',
    'KNOWLEDGE_BASE_ID': '${BEDROCK_KB_ID}',
    'DATA_SOURCE_ID': '${BEDROCK_DS_ID}',
    'KNOWLEDGE_BASE_BUCKET': '${KB_BUCKET}',
    'QUICKSIGHT_DATASET_ID': '${QUICKSIGHT_DATASET}',
    'AWS_ACCOUNT_ID': '${AWS_ACCOUNT_ID}'
}