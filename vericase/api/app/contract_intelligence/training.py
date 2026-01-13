"""
Training Service for Contract Intelligence
Manages training examples and prepares data for AI model improvement
"""

import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from .models import AITrainingExample

logger = logging.getLogger(__name__)


class TrainingService:
    """Service for managing AI training data"""

    def add_example(
        self,
        db: Session,
        contract_type_id: int,
        input_text: str,
        expected_output: Dict[str, Any],
        source_type: str = "manual",
        tags: List[str] = None,
    ) -> AITrainingExample:
        """Add a new training example"""
        example = AITrainingExample(
            contract_type_id=contract_type_id,
            input_text=input_text,
            expected_output=expected_output,
            source_type=source_type,
            tags=tags or [],
            confidence_score=1.0,  # Manual examples are high confidence
        )
        db.add(example)
        db.commit()
        db.refresh(example)
        return example

    def get_few_shot_examples(
        self, db: Session, contract_type_id: int, limit: int = 5, tags: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Get examples formatted for few-shot prompting"""
        query = db.query(AITrainingExample).filter(
            AITrainingExample.contract_type_id == contract_type_id,
            AITrainingExample.is_active == True,
        )

        if tags:
            # This is a simple overlap check, might need more complex logic for Postgres ARRAY
            # For now assuming exact match or simple containment if supported by DB dialect
            pass

        examples = (
            query.order_by(AITrainingExample.confidence_score.desc()).limit(limit).all()
        )

        return [
            {"input": ex.input_text, "output": ex.expected_output} for ex in examples
        ]


training_service = TrainingService()
