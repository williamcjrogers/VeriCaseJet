"""
Case Law Mining Service
Extracts structured data (patterns, issues, outcomes) from case law judgments using Bedrock.
"""

import json
import re
import logging
import uuid
from typing import Any, Dict, Optional, List

from sqlalchemy.orm import Session

from ..aws_services import aws_services
from ..models import CaseLaw, AppSetting
from ..ai_settings import get_ai_api_key, is_bedrock_enabled
from ..ai_providers import bedrock_available
from ..ai_runtime import complete_chat
from ..schemas.caselaw import CaseExtraction
from .caselaw_quant import caselaw_quant_extractor

logger = logging.getLogger(__name__)


class CaseLawMiningService:
    def __init__(self):
        self.aws = aws_services

    def _get_setting(self, db: Session, key: str, default: str) -> str:
        try:
            setting = db.query(AppSetting).filter(AppSetting.key == key).first()
            if setting and setting.value:
                return str(setting.value)
        except Exception:
            pass
        return default

    def _get_mining_provider_model(self, db: Session) -> tuple[str, str]:
        raw_value = self._get_setting(db, "caselaw_mining_model", "").strip()
        if raw_value:
            if ":" in raw_value:
                provider, model_id = raw_value.split(":", 1)
                return provider.strip(), model_id.strip()
            return "bedrock", raw_value.strip()

        # Dynamic default: prefer Bedrock if enabled, else fall back to key-based providers.
        if is_bedrock_enabled(db) and bedrock_available():
            return "bedrock", "amazon.nova-pro-v1:0"
        if get_ai_api_key("anthropic", db):
            return "anthropic", "claude-sonnet-4-20250514"
        if get_ai_api_key("openai", db):
            return "openai", "gpt-4o"
        if get_ai_api_key("gemini", db):
            return "gemini", "gemini-2.5-pro"
        return "openai", "gpt-4o"

    def _get_taxonomy(self, db: Session) -> List[str]:
        raw = self._get_setting(db, "caselaw_taxonomy", "").strip()
        if not raw:
            return []
        tags = []
        for line in raw.splitlines():
            cleaned = line.strip()
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
        return tags

    def _parse_case_uuid(self, case_id: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(case_id))
        except Exception:
            return None

    def _canonicalize_terms(self, values: List[str], taxonomy: List[str]) -> List[str]:
        if not values:
            return []
        if not taxonomy:
            return values
        canonical = {t.lower(): t for t in taxonomy}
        result: List[str] = []
        for item in values:
            if not item:
                continue
            mapped = canonical.get(item.lower(), item)
            if mapped not in result:
                result.append(mapped)
        return result

    async def mine_case(self, case_id: str, db: Session) -> Optional[Dict[str, Any]]:
        """
        Mine a single case for patterns and structured data.
        """
        case_uuid = self._parse_case_uuid(case_id)
        if case_uuid is None:
            logger.error("Invalid case id: %s", case_id)
            return None

        case = db.query(CaseLaw).filter(CaseLaw.id == case_uuid).first()
        if not case:
            logger.error(f"Case {case_id} not found")
            return None

        if case.extraction_status == "extracted" and case.extracted_analysis:
            return case.extracted_analysis

        case.extraction_status = "processing"
        db.commit()

        # 1. Fetch text content (from S3 or DB if available)
        # For MVP, we'll assume text is in 'summary' or we fetch from S3
        # In a real scenario, we'd fetch the full text from s3_key_curated
        text_content = await self._fetch_case_text(case)
        if not text_content:
            logger.error(f"No text content for case {case.neutral_citation}")
            case.extraction_status = "failed"
            db.commit()
            return None

        taxonomy = self._get_taxonomy(db)

        # 2. Construct Prompt
        prompt = self._construct_extraction_prompt(text_content, taxonomy=taxonomy)

        # 3. Invoke model (with fallbacks)
        provider, model_id = self._get_mining_provider_model(db)
        candidates: List[tuple[str, str]] = [(provider, model_id)]
        for candidate in [
            ("anthropic", "claude-sonnet-4-20250514"),
            ("openai", "gpt-4o"),
            ("gemini", "gemini-2.5-pro"),
            ("bedrock", "amazon.nova-pro-v1:0"),
        ]:
            if candidate not in candidates:
                candidates.append(candidate)

        last_error: str | None = None
        for provider_name, candidate_model in candidates:
            try:
                completion = await complete_chat(
                    provider=provider_name,
                    model_id=candidate_model,
                    prompt=prompt,
                    system_prompt="You are a legal expert AI. Return strict JSON only.",
                    db=db,
                    max_tokens=4096,
                    temperature=0,
                    task_type="caselaw_mining",
                    metadata={
                        "caselaw_id": str(case.id),
                        "caselaw_citation": case.neutral_citation,
                    },
                )

                # 4. Parse and Validate JSON
                extracted_data = self._parse_extraction(
                    completion, case, taxonomy=taxonomy
                )
                if not extracted_data:
                    raise RuntimeError("Invalid JSON extraction")

                # 5. Update Database
                payload = extracted_data.dict()

                # 5a. Quantitative extraction pass (best-effort, grounded excerpts)
                try:
                    quant_metadata = {
                        "caselaw_id": str(case.id),
                        "caselaw_citation": case.neutral_citation,
                    }
                    quant_candidates: List[tuple[str, str]] = [
                        (provider_name, candidate_model)
                    ]
                    for alt in [
                        ("anthropic", "claude-sonnet-4-20250514"),
                        ("openai", "gpt-4o"),
                        ("gemini", "gemini-2.5-pro"),
                        ("bedrock", "amazon.nova-pro-v1:0"),
                    ]:
                        if alt not in quant_candidates:
                            quant_candidates.append(alt)

                    quant: Dict[str, Any] | None = None
                    for q_provider, q_model in quant_candidates[:2]:
                        try:
                            attempt = await caselaw_quant_extractor.extract(
                                db=db,
                                provider=q_provider,
                                model_id=q_model,
                                text=text_content,
                                metadata=quant_metadata,
                            )
                        except Exception as e:
                            logger.warning(
                                "Quant extraction attempt failed for %s using %s/%s: %s",
                                case.neutral_citation,
                                q_provider,
                                q_model,
                                e,
                            )
                            continue

                        if not isinstance(attempt, dict):
                            continue
                        has_indicators = any(
                            attempt.get(key) is not None
                            for key in ("rfi_count", "change_order_count", "delay_days")
                        )
                        has_facts = bool(attempt.get("quant_facts"))
                        if has_facts or has_indicators:
                            quant = attempt
                            break

                    if isinstance(quant, dict):
                        if quant.get("quant_facts"):
                            payload["quant_facts"] = quant.get("quant_facts") or []
                        for key in ("rfi_count", "change_order_count", "delay_days"):
                            if quant.get(key) is not None:
                                payload[key] = quant.get(key)
                except Exception as e:
                    logger.warning(
                        "Quant extraction failed for %s: %s",
                        case.neutral_citation,
                        e,
                    )

                case.extracted_analysis = payload
                case.extraction_status = "extracted"
                db.commit()

                return payload
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Mining attempt failed for %s using %s/%s: %s",
                    case.neutral_citation,
                    provider_name,
                    candidate_model,
                    e,
                )

        logger.error(
            "Mining failed for %s after %d attempts: %s",
            case.neutral_citation,
            len(candidates),
            last_error or "unknown error",
        )
        case.extraction_status = "failed"
        db.commit()
        return None

    async def _fetch_case_text(self, case: CaseLaw) -> str:
        """Fetch text from S3 or fallback"""
        if case.full_text_preview:
            return case.full_text_preview

        s3_location = self._resolve_s3_location(case)
        if s3_location:
            bucket, key = s3_location
            try:
                obj = await self.aws._run_in_executor(
                    self.aws.s3.get_object, Bucket=bucket, Key=key
                )
                body_bytes = await self.aws._run_in_executor(obj["Body"].read)
                text = self._extract_text_from_curated(body_bytes)
                if text:
                    return text
            except Exception as e:
                logger.warning(
                    "Failed to fetch case text from S3 (%s/%s): %s",
                    bucket,
                    key,
                    e,
                )

        return case.summary or ""

    def _construct_extraction_prompt(self, text: str, *, taxonomy: List[str]) -> str:
        raw_text = text or ""
        if len(raw_text) <= 50000:
            excerpt = raw_text
        else:
            head = raw_text[:35000]
            tail = raw_text[-15000:]
            excerpt = f"{head}\n\n[...snip...]\n\n{tail}"
        taxonomy_block = ""
        if taxonomy:
            taxonomy_lines = "\n".join(f"- {t}" for t in taxonomy[:200])
            taxonomy_block = f"\n\nTag taxonomy (use these exact spellings when possible):\n{taxonomy_lines}"
        return f"""
You are a legal expert AI. Analyze the following judgment text and extract structured data.
Focus on construction/engineering disputes. If the case is not construction-related, leave construction_buckets empty.

Judgment Text:
{excerpt}{taxonomy_block}

Extract the following fields in strict JSON format:
- outcome: The overall outcome (e.g., "Appeal Allowed", "Claim Dismissed")
- issues: A list of legal issues. For each issue, provide:
    - issue_name: The name of the issue
    - legal_test: The legal test applied
    - key_factors_for: Factors supporting the winning side
    - key_factors_against: Factors supporting the losing side
    - holding: The court's decision on this issue
    - confidence: A score between 0.0 and 1.0
- citations: List of cases cited
- key_facts: List of key facts
- themes: High-level themes for trend analysis (e.g., payment notices, design liability)
- contentious_issues: Recurring contentious issues/points in dispute
- contract_form: Contract form if mentioned (e.g., JCT, NEC, FIDIC, bespoke)
- procurement_route: Delivery/procurement route if stated (e.g., design and build)
- key_clauses: Key clause or statutory references (e.g., HGCRA s.110, JCT clause 4.10)
- delay_causes: Causes of delay where relevant (e.g., design change, access restrictions)
- defect_types: Defect types/issues where relevant (e.g., cladding, fire stopping)
- tags: Normalized tags for auto-tagging and trend detection
- construction_buckets: Construction focus buckets (choose from: design, remediation, defect, delay, payment, variation, termination, safety, procurement)
- rfi_count: Number of RFIs (requests for information) mentioned, integer if stated
- change_order_count: Number of change orders/variations mentioned, integer if stated
- delay_days: Number of delay days mentioned, integer if stated

Output ONLY a single JSON object. Use empty arrays or null if unknown. No Markdown.
"""

    def _normalize_list(self, value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, list):
            items = []
            for item in value:
                if item is None:
                    continue
                text = str(item).strip()
                if text:
                    items.append(text)
            return items
        text_value = str(value).strip()
        return [text_value] if text_value else []

    def _merge_tags(self, *lists: List[str]) -> List[str]:
        combined: List[str] = []
        for items in lists:
            for item in items:
                if item and item not in combined:
                    combined.append(item)
        return combined

    def _issue_names(self, issues: Any) -> List[str]:
        if not isinstance(issues, list):
            return []
        names: List[str] = []
        for issue in issues:
            if isinstance(issue, dict):
                name = str(issue.get("issue_name") or "").strip()
                if name:
                    names.append(name)
        return names

    def _parse_optional_int(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)

        text = str(value).strip()
        if not text:
            return None
        match = re.search(r"\d+", text.replace(",", ""))
        if not match:
            return None
        try:
            return int(match.group(0))
        except ValueError:
            return None

    def _derive_construction_buckets(self, data: Dict[str, Any]) -> List[str]:
        buckets: List[str] = []
        mapping = {
            "design": [
                "design",
                "designer",
                "design responsibility",
                "fitness for purpose",
                "specification",
            ],
            "remediation": ["remediation", "remedial", "rectification", "repair"],
            "defect": ["defect", "defective", "workmanship", "latent defect", "snag"],
            "delay": ["delay", "extension of time", "eot", "programme"],
            "payment": ["payment", "pay less", "valuation", "adjudication"],
            "variation": [
                "variation",
                "change order",
                "change instruction",
                "variation order",
            ],
            "termination": ["termination", "repudiation", "determination"],
            "safety": ["safety", "fire", "cladding", "building regulations"],
            "procurement": ["procurement", "tender", "bid", "design and build", "pfi"],
        }

        text_parts: List[str] = []
        for key in (
            "themes",
            "contentious_issues",
            "tags",
            "delay_causes",
            "defect_types",
            "key_clauses",
            "construction_buckets",
        ):
            text_parts.extend(self._normalize_list(data.get(key)))

        text_parts.extend(self._issue_names(data.get("issues")))
        summary = str(data.get("summary") or "").strip()
        if summary:
            text_parts.append(summary)

        combined = " ".join(text_parts).lower()
        if not combined:
            return []

        for bucket, keywords in mapping.items():
            for keyword in keywords:
                if keyword in combined:
                    buckets.append(bucket)
                    break

        return buckets

    def _canonicalize_construction_buckets(self, buckets: List[str]) -> List[str]:
        allowed = {
            "design",
            "remediation",
            "defect",
            "delay",
            "payment",
            "variation",
            "termination",
            "safety",
            "procurement",
        }
        normalized: List[str] = []
        for bucket in buckets:
            key = str(bucket or "").strip().lower()
            if not key:
                continue
            if key not in allowed:
                continue
            if key not in normalized:
                normalized.append(key)
        return normalized

    def _parse_extraction(
        self, completion: str, case: CaseLaw, *, taxonomy: List[str]
    ) -> Optional[CaseExtraction]:
        """Parse JSON from LLM response"""
        try:
            # Find JSON block
            start = completion.find("{")
            end = completion.rfind("}")
            if start < 0 or end < 0 or end <= start:
                raise ValueError("No JSON object found in model response")

            json_str = completion[start : end + 1]
            data = json.loads(json_str)

            # Add required fields if missing from LLM output
            data["case_id"] = str(case.id)
            data["neutral_citation"] = case.neutral_citation
            if not data.get("summary"):
                data["summary"] = case.summary or "Auto-extracted"

            data["citations"] = self._normalize_list(data.get("citations"))
            data["key_facts"] = self._normalize_list(data.get("key_facts"))
            data["themes"] = self._normalize_list(data.get("themes"))
            data["contentious_issues"] = self._normalize_list(
                data.get("contentious_issues")
            )
            data["key_clauses"] = self._normalize_list(data.get("key_clauses"))
            data["delay_causes"] = self._normalize_list(data.get("delay_causes"))
            data["defect_types"] = self._normalize_list(data.get("defect_types"))
            data["tags"] = self._normalize_list(data.get("tags"))
            data["construction_buckets"] = self._canonicalize_construction_buckets(
                self._normalize_list(data.get("construction_buckets"))
            )
            data["rfi_count"] = self._parse_optional_int(data.get("rfi_count"))
            data["change_order_count"] = self._parse_optional_int(
                data.get("change_order_count")
            )
            data["delay_days"] = self._parse_optional_int(data.get("delay_days"))

            # Normalize issue fields into lists/strings so Pydantic validation passes
            normalized_issues: List[Dict[str, Any]] = []
            for issue in data.get("issues") or []:
                if not isinstance(issue, dict):
                    continue

                issue_name = str(issue.get("issue_name") or "").strip()
                if not issue_name:
                    continue
                issue["issue_name"] = issue_name

                holding = str(issue.get("holding") or "").strip()
                issue["holding"] = holding or "Unknown"

                confidence = issue.get("confidence")
                try:
                    confidence_value = float(confidence)
                except Exception:
                    confidence_value = 0.5
                confidence_value = max(0.0, min(1.0, confidence_value))
                issue["confidence"] = confidence_value

                legal_test = issue.get("legal_test")
                if isinstance(legal_test, str):
                    issue["legal_test"] = [legal_test]
                elif isinstance(legal_test, list):
                    issue["legal_test"] = self._normalize_list(legal_test)
                else:
                    issue["legal_test"] = []

                for key in ("key_factors_for", "key_factors_against"):
                    factors = issue.get(key)
                    if isinstance(factors, str):
                        issue[key] = [factors]
                    elif isinstance(factors, list):
                        issue[key] = self._normalize_list(factors)
                    else:
                        issue[key] = []

                normalized_issues.append(issue)
            data["issues"] = normalized_issues

            outcome = str(data.get("outcome") or "").strip()
            data["outcome"] = outcome or "Unknown"

            if data.get("contract_form") == "":
                data["contract_form"] = None
            if data.get("procurement_route") == "":
                data["procurement_route"] = None

            if not data["tags"]:
                data["tags"] = self._merge_tags(
                    data["themes"],
                    data["contentious_issues"],
                    data["delay_causes"],
                    data["defect_types"],
                )

            if not data["construction_buckets"]:
                data["construction_buckets"] = self._canonicalize_construction_buckets(
                    self._derive_construction_buckets(data)
                )

            # Canonicalize outputs against the admin-defined taxonomy where possible
            data["themes"] = self._canonicalize_terms(data["themes"], taxonomy)
            data["contentious_issues"] = self._canonicalize_terms(
                data["contentious_issues"], taxonomy
            )
            data["delay_causes"] = self._canonicalize_terms(
                data["delay_causes"], taxonomy
            )
            data["defect_types"] = self._canonicalize_terms(
                data["defect_types"], taxonomy
            )
            data["tags"] = self._canonicalize_terms(data["tags"], taxonomy)

            return CaseExtraction(**data)
        except Exception as e:
            logger.error(f"JSON parsing failed: {e}")
            return None

    def _resolve_s3_location(self, case: CaseLaw) -> Optional[tuple[str, str]]:
        if not case.s3_key_curated:
            return None

        if case.s3_key_curated.startswith("s3://"):
            path = case.s3_key_curated[5:]
            bucket, _, key = path.partition("/")
            if bucket and key:
                return bucket, key
            return None

        if not case.s3_bucket:
            return None

        return case.s3_bucket, case.s3_key_curated.lstrip("/")

    def _extract_text_from_curated(self, payload: bytes) -> str:
        raw_text = payload.decode("utf-8", errors="ignore")
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return raw_text

        if isinstance(data, dict):
            return (
                data.get("text") or data.get("content") or data.get("full_text") or ""
            )

        return raw_text


caselaw_miner = CaseLawMiningService()
