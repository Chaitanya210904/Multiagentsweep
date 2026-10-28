"""
Tool: rules.parse
Parses enterprise policy documents, guidelines, Markdown, TXT, JSON, and YAML files
into structured CompanyRuleDefinition objects with numbered rule IDs, categories, and severities.
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

from models.company_rules import CompanyRuleDefinition, RuleCategory, RuleSeverity


class RuleParserTool:
    """
    Parses rule files (PDF text, Markdown, DOC, TXT, JSON, YAML) into structured
    CompanyRuleDefinition objects with numbered rule IDs.
    """

    name = "rules.parse"
    description = (
        "Parses uploaded rule documents into structured CompanyRuleDefinition objects "
        "extracting numbered rule IDs (e.g. SEC-001), severity, categories, patterns, and remediations."
    )

    # Built-in enterprise corporate rule book used as baseline if no custom rule file is provided
    DEFAULT_ENTERPRISE_RULES: List[CompanyRuleDefinition] = [
        CompanyRuleDefinition(
            rule_id="RULE-SEC-001",
            title="Prohibit Hardcoded Credentials and Secrets",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            description="API keys, private keys, database passwords, and auth tokens must never be hardcoded in source code.",
            pattern=r"(?i)(password|secret|api_key|token|access_key)\s*=\s*['\"][A-Za-z0-9_\-\/+=]{8,}['\"]",
            file_patterns=["*.py", "*.js", "*.ts", "*.json", "*.yaml", "*.yml"],
            remediation="Extract credentials to environment variables or enterprise secret vaults (e.g. AWS Secrets Manager, HashiCorp Vault).",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-SEC-002",
            title="Prohibit Dangerous Dynamic Code Execution",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            description="Functions eval(), exec(), and os.system() must not be used with untrusted user input.",
            pattern=r"\b(eval|exec|os\.system)\s*\(",
            file_patterns=["*.py", "*.js", "*.ts"],
            remediation="Replace dynamic execution with safe AST parsers, literal_eval, or subprocess.run with argument arrays.",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-ARCH-001",
            title="Prohibit Direct SQL in API Controller Layer",
            category=RuleCategory.ARCHITECTURE,
            severity=RuleSeverity.HIGH,
            description="API route handlers and controllers must not construct or execute inline raw SQL queries directly.",
            pattern=r"(?i)(SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+.+\s+SET|DELETE\s+FROM)",
            file_patterns=["*api*", "*router*", "*controller*", "*route*"],
            remediation="Route database queries through designated repository or service layers instead of API controllers.",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-PRIV-001",
            title="Prohibit Logging of Plaintext Personally Identifiable Information (PII)",
            category=RuleCategory.DATA_PRIVACY,
            severity=RuleSeverity.HIGH,
            description="Personally Identifiable Information such as credit card numbers, SSNs, or email addresses must not be logged in plaintext.",
            pattern=r"(?i)log(ger)?\.(info|debug|error|warning)\(.*(ssn|credit_card|social_security|cvv)",
            file_patterns=["*.py", "*.js", "*.ts", "*.go", "*.java"],
            remediation="Sanitize or mask PII fields before passing them to logging frameworks.",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-NAME-001",
            title="Enforce Snake Case Function and Method Names in Python",
            category=RuleCategory.NAMING,
            severity=RuleSeverity.MEDIUM,
            description="All Python function and method definitions must use snake_case rather than camelCase.",
            pattern=r"def\s+[a-z]+[A-Z][a-zA-Z0-9]*\s*\(",
            file_patterns=["*.py"],
            remediation="Rename function to follow PEP 8 snake_case conventions (e.g. calculate_total instead of calculateTotal).",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-DEP-001",
            title="Prohibit Deprecated Insecure Networking Modules",
            category=RuleCategory.DEPENDENCIES,
            severity=RuleSeverity.HIGH,
            description="Insecure networking libraries such as telnetlib, urllib2, and ftplib are forbidden in production services.",
            pattern=r"(?i)(import\s+telnetlib|from\s+telnetlib|import\s+urllib2|from\s+urllib2)",
            file_patterns=["*.py"],
            remediation="Migrate to modern TLS-enabled HTTP client libraries such as httpx, requests, or urllib3.",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-STYLE-001",
            title="Prohibit Generic Exception Swallowing",
            category=RuleCategory.CODE_STYLE,
            severity=RuleSeverity.MEDIUM,
            description="Broad try-except blocks that pass silently without logging or re-raising mask critical defects.",
            pattern=r"except\s*:\s*\n\s*pass|except\s+Exception\s*:\s*\n\s*pass",
            file_patterns=["*.py"],
            remediation="Catch specific exceptions and log the diagnostic stack trace.",
        ),
    ]

    def parse_rules(
        self,
        rule_files_or_texts: Optional[List[str]] = None,
        explicit_definitions: Optional[List[CompanyRuleDefinition]] = None,
    ) -> List[CompanyRuleDefinition]:
        """
        Parses rules from files, text strings, or returns baseline rules.
        """
        parsed_rules: List[CompanyRuleDefinition] = []

        # 1. Include explicit definitions if passed
        if explicit_definitions:
            parsed_rules.extend(explicit_definitions)

        # 2. Parse from file paths or inline strings
        if rule_files_or_texts:
            for item in rule_files_or_texts:
                item_str = str(item).strip()
                if not item_str:
                    continue

                path = Path(item_str)
                if path.exists() and path.is_file():
                    content = path.read_text(encoding="utf-8", errors="replace")
                    rules_from_file = self._parse_content(content, source_name=path.name)
                    parsed_rules.extend(rules_from_file)
                else:
                    # Treat item directly as raw rule text / markdown
                    rules_from_text = self._parse_content(item_str, source_name="inline_policy")
                    parsed_rules.extend(rules_from_text)

        # 3. If no rules could be parsed, fallback to default enterprise rule book
        if not parsed_rules:
            parsed_rules = list(self.DEFAULT_ENTERPRISE_RULES)

        # Deduplicate by rule_id
        seen: Dict[str, CompanyRuleDefinition] = {}
        for r in parsed_rules:
            seen[r.rule_id] = r
        return list(seen.values())

    def _parse_content(self, text: str, source_name: str) -> List[CompanyRuleDefinition]:
        """Parses structured JSON/YAML or freeform Markdown/numbered rules."""
        # Check if text is JSON
        text_clean = text.strip()
        if text_clean.startswith("[") or text_clean.startswith("{"):
            try:
                data = json.loads(text_clean)
                rules_list = data if isinstance(data, list) else data.get("rules", [])
                res = []
                for entry in rules_list:
                    if isinstance(entry, dict) and "rule_id" in entry:
                        res.append(self._dict_to_rule(entry, source_name))
                if res:
                    return res
            except Exception:
                pass

        # Parse Markdown or numbered text format
        # e.g.:
        # ### RULE-SEC-001: Prohibit Hardcoded Credentials [CRITICAL]
        # Category: security
        # Description: API keys must not be hardcoded.
        # Pattern: ...
        # Remediation: ...
        return self._parse_markdown_rules(text, source_name)

    def _dict_to_rule(self, d: Dict[str, Any], source_name: str) -> CompanyRuleDefinition:
        """Converts dictionary to CompanyRuleDefinition with robust defaults."""
        sev_str = str(d.get("severity") or "high").lower()
        sev = RuleSeverity.HIGH
        for s in RuleSeverity:
            if s.value in sev_str:
                sev = s
                break

        cat_str = str(d.get("category") or "security").lower()
        cat = RuleCategory.SECURITY
        for c in RuleCategory:
            if c.value in cat_str:
                cat = c
                break

        fp = d.get("file_patterns") or d.get("files") or ["*"]
        if isinstance(fp, str):
            fp = [fp]

        return CompanyRuleDefinition(
            rule_id=str(d.get("rule_id") or "RULE-CUSTOM"),
            title=str(d.get("title") or "Company Policy Rule"),
            category=cat,
            severity=sev,
            description=str(d.get("description") or ""),
            pattern=d.get("pattern"),
            file_patterns=fp,
            remediation=str(d.get("remediation") or "Remediate according to company standards."),
            source_file=source_name,
        )

    def _parse_markdown_rules(self, text: str, source_name: str) -> List[CompanyRuleDefinition]:
        """Extracts numbered rules from markdown headings and key-value blocks."""
        results: List[CompanyRuleDefinition] = []

        # Regex finding headers like:
        # ## RULE-SEC-001: Prohibit Hardcoded Credentials [CRITICAL]
        # or ### [ARCH-012] Clean Architecture Boundary
        header_regex = re.compile(
            r"^(?:#{1,4}|\*+|-+)\s*(?:\[?([A-Z0-9_\-]+)\]?[:\s\-]+)([^\n\[]+)(?:\[([A-Z]+)\])?",
            re.MULTILINE,
        )

        matches = list(header_regex.finditer(text))
        if not matches:
            # Try bullet list format: - RULE-001: Description
            bullet_regex = re.compile(
                r"^[\*\-]\s+([A-Z0-9_\-]+)[:\s\-]+([^\n]+)",
                re.MULTILINE,
            )
            for bm in bullet_regex.finditer(text):
                rid = bm.group(1).strip()
                title = bm.group(2).strip()
                results.append(
                    CompanyRuleDefinition(
                        rule_id=rid,
                        title=title,
                        category=RuleCategory.SECURITY,
                        severity=RuleSeverity.HIGH,
                        description=title,
                        remediation="Ensure compliance with stated policy.",
                        source_file=source_name,
                    )
                )
            return results

        for i, m in enumerate(matches):
            rule_id = m.group(1).strip()
            title = m.group(2).strip()
            sev_tag = m.group(3).strip().lower() if m.group(3) else "high"

            sev = RuleSeverity.HIGH
            for s in RuleSeverity:
                if s.value in sev_tag:
                    sev = s
                    break

            # Block content until next header
            start_pos = m.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[start_pos:end_pos]

            desc = ""
            remediation = "Ensure compliance with enterprise policy."
            cat = RuleCategory.SECURITY
            pattern = None
            file_patterns = ["*"]

            for line in block.splitlines():
                line_str = line.strip()
                if line_str.lower().startswith("category:"):
                    c_val = line_str.split(":", 1)[1].strip().lower()
                    for c in RuleCategory:
                        if c.value in c_val:
                            cat = c
                            break
                elif line_str.lower().startswith("severity:"):
                    s_val = line_str.split(":", 1)[1].strip().lower()
                    for s in RuleSeverity:
                        if s.value in s_val:
                            sev = s
                            break
                elif line_str.lower().startswith("pattern:"):
                    pattern = line_str.split(":", 1)[1].strip().strip("`").strip("'").strip('"')
                elif line_str.lower().startswith("files:") or line_str.lower().startswith("file_patterns:"):
                    f_val = line_str.split(":", 1)[1].strip()
                    file_patterns = [p.strip() for p in f_val.split(",") if p.strip()]
                elif line_str.lower().startswith("remediation:"):
                    remediation = line_str.split(":", 1)[1].strip()
                elif line_str and not desc:
                    desc = line_str

            results.append(
                CompanyRuleDefinition(
                    rule_id=rule_id,
                    title=title,
                    category=cat,
                    severity=sev,
                    description=desc or title,
                    pattern=pattern,
                    file_patterns=file_patterns,
                    remediation=remediation,
                    source_file=source_name,
                )
            )

        return results
