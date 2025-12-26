"""
Generates the Step Functions ASL definition for the Case Law Mining Workflow.
"""

import json


def generate_asl():
    workflow = {
        "Comment": "Case Law Pattern Mining Workflow",
        "StartAt": "ProcessBatch",
        "States": {
            "ProcessBatch": {
                "Type": "Map",
                "ItemsPath": "$.cases",
                "MaxConcurrency": 5,
                "Iterator": {
                    "StartAt": "MineCase",
                    "States": {
                        "MineCase": {
                            "Type": "Task",
                            "Resource": "${MiningLambdaArn}",  # Placeholder
                            "Parameters": {"case_id.$": "$.id"},
                            "Retry": [
                                {
                                    "ErrorEquals": ["States.TaskFailed"],
                                    "IntervalSeconds": 2,
                                    "MaxAttempts": 3,
                                    "BackoffRate": 2.0,
                                }
                            ],
                            "End": True,
                        }
                    },
                },
                "End": True,
            }
        },
    }

    print(json.dumps(workflow, indent=2))


if __name__ == "__main__":
    generate_asl()
