"""
Production Dashboard API - Real-time AWS Infrastructure Monitoring
Live metrics for EKS, RDS, S3, and application health
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import boto3
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from .config import settings
from .models import User, UserRole
from .security import current_user
from .db import get_db, engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["production-dashboard"])


class ProductionMonitor:
    """Real-time production infrastructure monitoring"""

    def __init__(self):
        self.cloudwatch = boto3.client('cloudwatch', region_name=settings.AWS_REGION)
        self.eks = boto3.client('eks', region_name=settings.AWS_REGION)
        self.rds = boto3.client('rds', region_name=settings.AWS_REGION)
        self.s3 = boto3.client('s3', region_name=settings.AWS_REGION)
        self.ec2 = boto3.client('ec2', region_name=settings.AWS_REGION)

    async def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health metrics"""
        logger.info("Fetching system health metrics...")

        try:
            health = {
                'timestamp': datetime.now().isoformat(),
                'status': 'healthy',
                'eks': await self._get_eks_metrics(),
                'rds': await self._get_rds_metrics(),
                's3': await self._get_s3_metrics(),
                'application': await self._get_application_metrics(),
                'errors': await self._get_recent_errors()
            }

            # Determine overall status
            if health['errors']['count'] > 50:
                health['status'] = 'degraded'
            if health['rds']['connections_percent'] > 90:
                health['status'] = 'warning'

            return health

        except Exception as e:
            logger.error(f"Error fetching system health: {e}", exc_info=True)
            return {
                'timestamp': datetime.now().isoformat(),
                'status': 'error',
                'error': str(e)
            }

    async def _get_eks_metrics(self) -> Dict[str, Any]:
        """Get EKS cluster metrics"""
        try:
            cluster_name = 'vericase-cluster'  # Your cluster name

            # Get cluster info
            cluster = self.eks.describe_cluster(name=cluster_name)
            cluster_info = cluster['cluster']

            # Get node count via EC2 (nodes are EC2 instances)
            nodes = self.ec2.describe_instances(
                Filters=[
                    {'Name': 'tag:eks:cluster-name', 'Values': [cluster_name]},
                    {'Name': 'instance-state-name', 'Values': ['running']}
                ]
            )

            node_count = sum(len(r['Instances']) for r in nodes['Reservations'])

            # Get pod metrics from CloudWatch
            pod_metrics = await self._get_cloudwatch_metric(
                namespace='ContainerInsights',
                metric_name='pod_number_of_running_pods',
                dimensions=[{'Name': 'ClusterName', 'Value': cluster_name}]
            )

            return {
                'status': cluster_info['status'],
                'version': cluster_info['version'],
                'endpoint': cluster_info.get('endpoint', 'N/A'),
                'node_count': node_count,
                'pod_count': pod_metrics.get('value', 'N/A'),
                'created_at': cluster_info['createdAt'].isoformat() if 'createdAt' in cluster_info else None
            }

        except Exception as e:
            logger.error(f"Error getting EKS metrics: {e}")
            return {
                'status': 'unknown',
                'error': str(e)
            }

    async def _get_rds_metrics(self) -> Dict[str, Any]:
        """Get RDS database metrics"""
        try:
            db_instance = 'vericase-prod'  # Your RDS instance name

            # Get instance info
            response = self.rds.describe_db_instances(
                DBInstanceIdentifier=db_instance
            )

            db_info = response['DBInstances'][0]

            # Get CloudWatch metrics
            cpu = await self._get_cloudwatch_metric(
                namespace='AWS/RDS',
                metric_name='CPUUtilization',
                dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance}]
            )

            connections = await self._get_cloudwatch_metric(
                namespace='AWS/RDS',
                metric_name='DatabaseConnections',
                dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance}]
            )

            free_memory = await self._get_cloudwatch_metric(
                namespace='AWS/RDS',
                metric_name='FreeableMemory',
                dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance}]
            )

            free_storage = await self._get_cloudwatch_metric(
                namespace='AWS/RDS',
                metric_name='FreeStorageSpace',
                dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance}]
            )

            # Calculate percentages
            allocated_storage_gb = db_info.get('AllocatedStorage', 0)
            free_storage_gb = free_storage.get('value', 0) / (1024**3) if free_storage.get('value') else 0
            storage_used_percent = ((allocated_storage_gb - free_storage_gb) / allocated_storage_gb * 100) if allocated_storage_gb > 0 else 0

            max_connections = 100  # Default, adjust based on instance type
            connections_percent = (connections.get('value', 0) / max_connections * 100) if connections.get('value') else 0

            return {
                'status': db_info.get('DBInstanceStatus', 'unknown'),
                'engine': f"{db_info.get('Engine', 'unknown')} {db_info.get('EngineVersion', '')}",
                'instance_class': db_info.get('DBInstanceClass', 'unknown'),
                'cpu_percent': round(cpu.get('value', 0), 2),
                'connections': int(connections.get('value', 0)),
                'connections_percent': round(connections_percent, 2),
                'memory_free_mb': round(free_memory.get('value', 0) / (1024**2), 2) if free_memory.get('value') else 0,
                'storage_allocated_gb': allocated_storage_gb,
                'storage_free_gb': round(free_storage_gb, 2),
                'storage_used_percent': round(storage_used_percent, 2),
                'multi_az': db_info.get('MultiAZ', False),
                'endpoint': db_info.get('Endpoint', {}).get('Address', 'N/A')
            }

        except Exception as e:
            logger.error(f"Error getting RDS metrics: {e}")
            return {
                'status': 'unknown',
                'error': str(e)
            }

    async def _get_s3_metrics(self) -> Dict[str, Any]:
        """Get S3 bucket metrics"""
        try:
            bucket_name = settings.S3_BUCKET

            # Get bucket size from CloudWatch
            bucket_size = await self._get_cloudwatch_metric(
                namespace='AWS/S3',
                metric_name='BucketSizeBytes',
                dimensions=[
                    {'Name': 'BucketName', 'Value': bucket_name},
                    {'Name': 'StorageType', 'Value': 'StandardStorage'}
                ],
                period=86400  # 24 hours
            )

            object_count = await self._get_cloudwatch_metric(
                namespace='AWS/S3',
                metric_name='NumberOfObjects',
                dimensions=[
                    {'Name': 'BucketName', 'Value': bucket_name},
                    {'Name': 'StorageType', 'Value': 'AllStorageTypes'}
                ],
                period=86400  # 24 hours
            )

            size_gb = bucket_size.get('value', 0) / (1024**3) if bucket_size.get('value') else 0

            # Estimate cost (S3 Standard pricing ~$0.023/GB/month)
            estimated_monthly_cost = size_gb * 0.023

            return {
                'bucket_name': bucket_name,
                'size_bytes': bucket_size.get('value', 0),
                'size_gb': round(size_gb, 2),
                'object_count': int(object_count.get('value', 0)),
                'estimated_monthly_cost_usd': round(estimated_monthly_cost, 2),
                'region': settings.AWS_REGION
            }

        except Exception as e:
            logger.error(f"Error getting S3 metrics: {e}")
            return {
                'bucket_name': settings.S3_BUCKET,
                'error': str(e)
            }

    async def _get_application_metrics(self) -> Dict[str, Any]:
        """Get application-level metrics from database"""
        try:
            with engine.connect() as conn:
                # Document counts
                doc_result = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_documents,
                        SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_documents,
                        SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) as processing_documents,
                        SUM(CASE WHEN status = 'ERROR' THEN 1 ELSE 0 END) as error_documents,
                        SUM(size) as total_size_bytes
                    FROM documents
                """))
                doc_stats = doc_result.fetchone()

                # Recent uploads (last 24 hours)
                recent_result = conn.execute(text("""
                    SELECT COUNT(*) as recent_uploads
                    FROM documents
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                """))
                recent_stats = recent_result.fetchone()

                # Case counts
                case_result = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_cases,
                        SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_cases
                    FROM cases
                """))
                case_stats = case_result.fetchone()

                # User counts
                user_result = conn.execute(text("""
                    SELECT
                        COUNT(*) as total_users,
                        SUM(CASE WHEN is_active = true THEN 1 ELSE 0 END) as active_users
                    FROM users
                """))
                user_stats = user_result.fetchone()

                return {
                    'documents': {
                        'total': doc_stats[0] if doc_stats else 0,
                        'completed': doc_stats[1] if doc_stats else 0,
                        'processing': doc_stats[2] if doc_stats else 0,
                        'errors': doc_stats[3] if doc_stats else 0,
                        'total_size_gb': round((doc_stats[4] or 0) / (1024**3), 2)
                    },
                    'recent_activity': {
                        'uploads_24h': recent_stats[0] if recent_stats else 0
                    },
                    'cases': {
                        'total': case_stats[0] if case_stats else 0,
                        'active': case_stats[1] if case_stats else 0
                    },
                    'users': {
                        'total': user_stats[0] if user_stats else 0,
                        'active': user_stats[1] if user_stats else 0
                    }
                }

        except Exception as e:
            logger.error(f"Error getting application metrics: {e}")
            return {
                'error': str(e)
            }

    async def _get_recent_errors(self) -> Dict[str, Any]:
        """Get recent errors from CloudWatch Logs"""
        try:
            logs_client = boto3.client('logs', region_name=settings.AWS_REGION)

            # Query CloudWatch Logs for errors in the last hour
            log_group = '/aws/eks/vericase/api'  # Adjust to your log group
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=1)

            try:
                response = logs_client.filter_log_events(
                    logGroupName=log_group,
                    startTime=int(start_time.timestamp() * 1000),
                    endTime=int(end_time.timestamp() * 1000),
                    filterPattern='ERROR'
                )

                errors = []
                for event in response.get('events', [])[:10]:  # Get last 10 errors
                    errors.append({
                        'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                        'message': event['message'][:200]  # Truncate long messages
                    })

                return {
                    'count': len(response.get('events', [])),
                    'recent': errors
                }

            except logs_client.exceptions.ResourceNotFoundException:
                logger.warning(f"Log group {log_group} not found")
                return {'count': 0, 'recent': [], 'note': 'Log group not configured'}

        except Exception as e:
            logger.error(f"Error getting recent errors: {e}")
            return {
                'count': 0,
                'recent': [],
                'error': str(e)
            }

    async def _get_cloudwatch_metric(
        self,
        namespace: str,
        metric_name: str,
        dimensions: List[Dict[str, str]],
        period: int = 300,
        stat: str = 'Average'
    ) -> Dict[str, Any]:
        """Generic CloudWatch metric retrieval"""
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(minutes=5)

            response = self.cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[stat]
            )

            datapoints = response.get('Datapoints', [])
            if datapoints:
                # Get most recent datapoint
                latest = max(datapoints, key=lambda x: x['Timestamp'])
                return {
                    'value': latest.get(stat),
                    'timestamp': latest['Timestamp'].isoformat(),
                    'unit': latest.get('Unit', 'None')
                }

            return {'value': None, 'note': 'No data available'}

        except Exception as e:
            logger.error(f"Error getting CloudWatch metric {metric_name}: {e}")
            return {'value': None, 'error': str(e)}


# Global monitor instance
production_monitor = ProductionMonitor()


@router.get("/system-health")
async def get_system_health(
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Get real-time system health metrics

    Requires authentication. Returns comprehensive health data including:
    - EKS cluster status and metrics
    - RDS database performance
    - S3 storage usage
    - Application statistics
    - Recent errors
    """
    try:
        health = await production_monitor.get_system_health()
        return health

    except Exception as e:
        logger.error(f"Error in system health endpoint: {e}")
        raise HTTPException(500, "Failed to fetch system health")


@router.get("/eks")
async def get_eks_metrics(user: User = Depends(current_user)):
    """Get detailed EKS cluster metrics"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin access required")

    try:
        metrics = await production_monitor._get_eks_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(500, f"Error fetching EKS metrics: {str(e)}")


@router.get("/rds")
async def get_rds_metrics(user: User = Depends(current_user)):
    """Get detailed RDS database metrics"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin access required")

    try:
        metrics = await production_monitor._get_rds_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(500, f"Error fetching RDS metrics: {str(e)}")


@router.get("/s3")
async def get_s3_metrics(user: User = Depends(current_user)):
    """Get detailed S3 storage metrics"""
    try:
        metrics = await production_monitor._get_s3_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(500, f"Error fetching S3 metrics: {str(e)}")


@router.get("/costs/estimate")
async def get_cost_estimate(user: User = Depends(current_user)):
    """Get estimated monthly AWS costs"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin access required")

    try:
        health = await production_monitor.get_system_health()

        # Rough cost estimates (adjust based on your actual usage)
        costs = {
            'eks': {
                'cluster': 73.0,  # ~$0.10/hour
                'nodes': health['eks'].get('node_count', 0) * 50,  # ~$50/node/month (t3.medium)
                'total': 73.0 + (health['eks'].get('node_count', 0) * 50)
            },
            'rds': {
                'instance': 100.0,  # Varies by instance type
                'storage': health['rds'].get('storage_allocated_gb', 0) * 0.115,  # $0.115/GB/month
                'total': 100.0 + (health['rds'].get('storage_allocated_gb', 0) * 0.115)
            },
            's3': {
                'storage': health['s3'].get('estimated_monthly_cost_usd', 0),
                'requests': 5.0,  # Estimate for API requests
                'total': health['s3'].get('estimated_monthly_cost_usd', 0) + 5.0
            },
            'other': {
                'cloudwatch': 10.0,
                'data_transfer': 20.0,
                'total': 30.0
            }
        }

        costs['total_monthly_estimate'] = sum([
            costs['eks']['total'],
            costs['rds']['total'],
            costs['s3']['total'],
            costs['other']['total']
        ])

        return costs

    except Exception as e:
        logger.error(f"Error calculating cost estimate: {e}")
        raise HTTPException(500, "Failed to calculate costs")
