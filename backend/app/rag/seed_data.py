SEED_DOCUMENTS = [
    {
        "title": "VPN Connection Troubleshooting Guide",
        "content": (
            "This guide covers common VPN connection issues and their resolutions. "
            "If users cannot connect to the corporate VPN, first verify their internet connection is active "
            "by pinging a public address like 8.8.8.8. If the internet is working, check that the VPN client "
            "software is up to date — versions older than 6 months often have certificate expiry issues.\n\n"
            "For Windows clients: Open the VPN client, go to Settings > Diagnostics, and run the connection "
            "test. Error code 691 indicates invalid credentials — the user should reset their domain password "
            "via the self-service portal. Error code 812 indicates the RADIUS server is unreachable, which "
            "usually means the network team needs to check firewall rules on port 1723.\n\n"
            "Split tunneling is enabled by default: only corporate traffic routes through the VPN. "
            "If a user needs full tunneling (e.g., for compliance scanning), they can request it via the "
            "IT portal with manager approval. Connection timeouts after 30 seconds of inactivity can be "
            "adjusted in the client config file at C:\\ProgramData\\VPNClient\\config.ini."
        ),
        "metadata": {"category": "network", "author": "IT", "version": "2.1"},
    },
    {
        "title": "Password Reset Procedure",
        "content": (
            "Password resets are handled through the self-service portal at reset.acme.com for standard users. "
            "The user must verify their identity using either SMS to their registered phone number or email "
            "to their recovery address. After verification, they can set a new password that meets complexity "
            "requirements: minimum 12 characters, at least one uppercase, one lowercase, one digit, and one "
            "special character. Passwords cannot be one of the last 24 used passwords.\n\n"
            "For users who cannot access the self-service portal (locked out or forgotten recovery methods), "
            "an IT administrator can perform a manual reset. The admin must verify the user's identity via "
            "manager approval ticket. Manual resets follow the same complexity rules. After reset, the user "
            "will be prompted to change their password on next login.\n\n"
            "Service accounts and privileged accounts require separate procedures. Service account passwords "
            "are managed through CyberArk and rotate automatically every 90 days. Emergency resets bypass "
            "the self-service and require two-approval workflow: the user's manager plus a director-level "
            "approval. All password reset events are logged to the SIEM with user ID, timestamp, and method."
        ),
        "metadata": {"category": "iam", "author": "Security", "version": "3.0"},
    },
    {
        "title": "Software Installation Policy",
        "content": (
            "All software installations on company-managed devices must be approved through the IT request "
            "portal. The approved software catalog includes: Microsoft Office 365, Slack, Zoom, Visual Studio "
            "Code, Adobe Acrobat Reader, 7-Zip, and the corporate VPN client. Software not on the approved "
            "list requires a business justification and security review before installation.\n\n"
            "Users with standard accounts cannot install software locally — they must submit a request via "
            "the IT portal. The request routes to the user's manager for approval, then to IT for installation. "
            "Standard installations are completed within 2 business days. Emergency installations (same-day) "
            "are available for critical business needs with director-level approval.\n\n"
            "Developers may request admin rights for their machines through a separate approval process. "
            "Admin rights are granted for 30-day periods and must be renewed. All software installed under "
            "admin rights is automatically inventoried by the endpoint management system. Unauthorized "
            "software detected during compliance scans triggers an automated ticket to the IT security team "
            "and a notification to the user's manager."
        ),
        "metadata": {"category": "compliance", "author": "IT", "version": "1.4"},
    },
    {
        "title": "Hardware Replacement Workflow",
        "content": (
            "Hardware replacement requests are initiated through the IT Asset Management portal. The user "
            "submits a request specifying the device type, current asset tag, and reason for replacement "
            "(damage, performance, end-of-life, or upgrade). Requests are automatically categorized: "
            "damage and end-of-life are high priority, performance and upgrade are standard priority.\n\n"
            "Standard replacement workflow: IT receives the request, verifies warranty status, and issues "
            "a replacement within 5 business days. The user receives a shipping label to return the old "
            "device. Data migration from the old device is the user's responsibility — backup critical "
            "files to OneDrive before the replacement arrives. Laptops are pre-configured with the "
            "standard image (Windows 11, Office 365, VPN, antivirus).\n\n"
            "Urgent replacements (within 24 hours) are available for critical roles with VP-level approval. "
            "The IT team maintains a pool of 10 pre-configured laptops for urgent replacements. Upon "
            "receiving the new device, the user must log in with their corporate credentials, verify "
            "the device is enrolled in Intune, and confirm data restore within 48 hours. The old device "
            "must be returned within 15 calendar days or the user's department is charged the full "
            "replacement cost."
        ),
        "metadata": {"category": "procurement", "author": "IT", "version": "1.2"},
    },
    {
        "title": "Data Breach Incident Response Plan",
        "content": (
            "This plan defines the process for detecting, containing, and remediating data breaches. "
            "Upon breach detection (alert from SIEM, user report, or third-party notification), the "
            "incident responder on duty follows these phases. Phase 1 — Containment: isolate affected "
            "systems from the network within 15 minutes, preserve forensic evidence by taking memory "
            "and disk snapshots, and document all findings in the incident tracking system.\n\n"
            "Phase 2 — Assessment: the security team determines the scope of the breach — what data "
            "was accessed, how many records, which systems were compromised. This phase must be "
            "completed within 4 hours. If PII or financial data is involved, legal is notified immediately. "
            "The assessment includes log review, user account audit, and vulnerability scan of affected systems.\n\n"
            "Phase 3 — Notification: affected users must be notified within 72 hours of breach confirmation "
            "per GDPR and CCPA requirements. Notifications include what data was compromised, what actions "
            "the company is taking, and steps the user should take (password reset, credit monitoring). "
            "Phase 4 — Remediation: apply patches, rotate all credentials on affected systems, and "
            "implement additional monitoring. A post-incident review is conducted within 30 days to "
            "identify process improvements and update the incident response playbook."
        ),
        "metadata": {"category": "security", "author": "Security", "version": "2.0"},
    },
    {
        "title": "Email Migration to Office 365",
        "content": (
            "This document outlines the process for migrating on-premises Exchange mailboxes to Office 365. "
            "Pre-migration: ensure all mailboxes are under 50 GB, remove any orphaned mailboxes, and verify "
            "that Outlook clients are version 2016 or newer. Run the Microsoft IdFix tool to clean up "
            "directory sync issues before migration. Cutover migration is used for deployments under 500 "
            "mailboxes; staged migration for larger deployments.\n\n"
            "Migration steps: Day 1 — sync identities via Azure AD Connect, verify mail flow from on-prem "
            "to cloud. Days 2-5 — migrate mailboxes in batches of 50, starting with test users and pilot "
            "group. After each batch, verify mailbox access, calendar functionality, and email forwarding. "
            "Day 6 — switch MX records to point to Exchange Online. Day 7 — decommission on-prem Exchange "
            "server after confirming all mailboxes are migrated and mail flow is stable.\n\n"
            "Post-migration: users may need to create a new Outlook profile with their new Office 365 "
            "settings. PST files are not automatically migrated — users must import them manually via "
            "the PST Import Service in the Exchange admin center. Shared mailboxes are migrated with "
            "permissions preserved. Distribution groups are migrated via directory synchronization. "
            "Rollback plan: if critical issues are found within 72 hours of cutover, revert MX records "
            "to on-prem and resume from last backup."
        ),
        "metadata": {"category": "migration", "author": "Infrastructure", "version": "1.1"},
    },
    {
        "title": "Server Patching Schedule",
        "content": (
            "Server patching follows a monthly cycle aligned with Microsoft Patch Tuesday. Patch Tuesday "
            "updates are reviewed by the infrastructure team within 48 hours of release. Critical and "
            "security patches are applied within 7 days. Non-critical patches are applied during the "
            "monthly maintenance window on the third Saturday of each month from 2:00 AM to 6:00 AM.\n\n"
            "Servers are grouped into rings: Ring 1 (development and test servers) patched first, "
            "Ring 2 (non-production) patched 3 days later if no issues in Ring 1, and Ring 3 (production) "
            "patched after 7 days of Ring 2 stability. Each server must have a recent backup before "
            "patching — backups are verified by restore test on a sample of 5% of servers per cycle.\n\n"
            "After patching, each server runs a health check suite: uptime verification, service status "
            "checks, port availability, and application health endpoint. Servers failing health checks "
            "are rolled back to the pre-patch snapshot and flagged for root cause analysis. The monthly "
            "patch report is distributed to IT management showing compliance rate, failed patches, and "
            "rollback events. Quarterly exception windows can be requested for servers that cannot"
            " tolerate downtime during standard maintenance windows."
        ),
        "metadata": {"category": "maintenance", "author": "Infrastructure", "version": "1.3"},
    },
    {
        "title": "Employee Offboarding Checklist",
        "content": (
            "When an employee leaves the company, the offboarding process begins automatically when the "
            "HR system updates the employee status to terminated. The IT offboarding checklist executes "
            "sequentially to ensure no access is missed. Step 1 (within 1 hour of termination): disable "
            "Active Directory account, revoke VPN access, and remove from all distribution lists.\n\n"
            "Step 2 (within 4 hours): transfer OneDrive files to manager, forward email with autoresponder, "
            "and revoke SaaS application access (Salesforce, Jira, Confluence, Slack). The manager receives "
            "a notification with instructions for file review and retention period (30 days by default). "
            "Step 3 (within 24 hours): disable mobile device access via Intune, revoke API tokens, and "
            "rotate service account passwords that the departing employee had access to.\n\n"
            "Step 4 (within 5 business days): the employee returns equipment — laptop, monitor, badge, "
            "and any company-owned peripherals. Equipment is checked against the asset inventory. Missing "
            "equipment triggers a notification to HR for cost recovery. The laptop is wiped and re-imaged "
            "before being added to the spare pool. Audit logs for the departing employee's account access "
            "are reviewed for any suspicious activity in the 30 days preceding termination."
        ),
        "metadata": {"category": "hr-it", "author": "IT", "version": "2.2"},
    },
    {
        "title": "API Rate Limiting Best Practices",
        "content": (
            "Rate limiting protects API services from abuse and ensures fair resource allocation. "
            "The recommended approach is token bucket rate limiting — each client receives a bucket of "
            "N tokens that refills at R tokens per second. Standard limits: 1000 requests per minute "
            "for public endpoints, 5000 requests per minute for authenticated endpoints, and 10000 "
            "requests per minute for internal service-to-service endpoints.\n\n"
            "Clients exceeding rate limits receive HTTP 429 Too Many Requests responses with a "
            "Retry-After header indicating when they can retry. Responses should also include "
            "X-RateLimit-Limit, X-RateLimit-Remaining, and X-RateLimit-Reset headers so clients "
            "can implement proper backoff strategies. Exponential backoff with jitter is the "
            "recommended retry strategy: start with 1 second delay, double each retry up to 60 seconds, "
            "and add random jitter of 0-1000ms to prevent thundering herd problems.\n\n"
            "Rate limit tracking is stored in Redis with TTL matching the rate limit window. "
            "Distributed rate limiting uses Redis INCR with expiry. For critical production APIs, "
            "use a sliding window algorithm instead of fixed window to avoid burst spikes at window "
            "boundaries. Monitor rate limit hit rates in Grafana with alerts at 80% threshold. "
            "Emergency rate limit increases can be approved for 24-hour windows during launch events."
        ),
        "metadata": {"category": "development", "author": "Engineering", "version": "1.0"},
    },
    {
        "title": "Database Backup and Recovery SOP",
        "content": (
            "This SOP covers backup and recovery procedures for production databases. Three backup "
            "types are maintained: full backups (weekly, Sunday 2 AM), differential backups (daily, "
            "incremental from last full backup), and transaction log backups (every 15 minutes for "
            "production databases). The recovery point objective (RPO) is 15 minutes, and the recovery "
            "time objective (RTO) is 4 hours for critical databases.\n\n"
            "Backups are stored in three locations: local disk (fastest recovery, retained 7 days), "
            "network storage (retained 30 days), and off-site cold storage (retained 1 year for "
            "compliance purposes). All backups are encrypted using AES-256, and backup integrity "
            "is verified by checksum validation after each backup job. Backup monitoring alerts the "
            "on-call DBA if any job fails or if backup size deviates by more than 20% from baseline.\n\n"
            "Recovery procedure: the requestor submits a recovery ticket with database name, requested "
            "point-in-time, and justification. The DBA validates the request, selects the appropriate "
            "backup chain, and restores to a staging environment first for verification. After the "
            "requestor confirms data integrity, the restored database is promoted to production. "
            "A quarterly recovery drill tests the full restore process using random databases — "
            "results are documented and any issues are remediated before the next drill."
        ),
        "metadata": {"category": "operations", "author": "Infrastructure", "version": "2.0"},
    },
    {
        "title": "Work Order Escalation Matrix",
        "content": (
            "Work orders are categorized by priority, and each priority level has defined response and "
            "resolution SLAs. Priority 1 (critical): service outage affecting 50+ users, security breach, "
            "or data loss. Response time: 15 minutes. Resolution target: 4 hours. Escalation path: "
            "L1 technician → L2 team lead (30 min) → L3 engineering manager (1 hour) → VP of IT (2 hours).\n\n"
            "Priority 2 (high): service degradation affecting 10-49 users, single-user data loss, or "
            "security policy violation. Response time: 1 hour. Resolution target: 8 hours. Escalation: "
            "L1 technician → L2 engineer (2 hours) → L3 manager (4 hours). Priority 3 (medium): "
            "individual user issue with workaround available, software installation request, or "
            "hardware replacement. Response time: 4 hours. Resolution target: 3 business days.\n\n"
            "Priority 4 (low): informational requests, documentation updates, or feature suggestions. "
            "Response time: 8 hours. Resolution target: 10 business days. Escalation for any priority "
            "can be requested by the user at any time if their issue is not progressing. The escalation "
            "must include a reason and is logged in the ticket system. Repeated escalations on the same "
            "issue trigger a management review of the handling team's processes."
        ),
        "metadata": {"category": "process", "author": "IT", "version": "1.5"},
    },
    {
        "title": "LLM Output Validation Rules",
        "content": (
            "This document defines validation rules for LLM-generated outputs used in automated workflows. "
            "All LLM outputs must pass the following checks before being accepted by downstream systems. "
            "Check 1 — Structure validation: the output must match the expected JSON schema (defined "
            "per workflow). Schema violations cause automatic rejection with error code SCHEMA_ERROR.\n\n"
            "Check 2 — Hallucination detection: the LLM must cite specific source chunks from the "
            "retrieved documents. If the output references facts not present in any source chunk, "
            "the confidence score is reduced proportionally. Outputs with confidence below 0.3 are "
            "automatically rejected. Check 3 — PII scanning: the output is scanned for email addresses, "
            "phone numbers, social security numbers, and credit card patterns. PII detection triggers "
            "automatic redaction and a security alert.\n\n"
            "Check 4 — Business rule compliance: the output must satisfy domain-specific rules configured "
            "per workflow. Example rules: critical priority resolutions must include at least 2 action items; "
            "all resolutions must reference at least one KB document; confidence must not exceed a threshold "
            "derived from the average similarity score of source chunks. Outputs failing any check are "
            "logged with the specific rule violated and returned to the worker agent for regeneration "
            "with the validation error included in the prompt context."
        ),
        "metadata": {"category": "ai-governance", "author": "AI Engineering", "version": "1.0"},
    },
]
