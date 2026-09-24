# Azure FinOps & Serverless VM Runtime Enforcer

An autonomous, event-driven FinOps automation solution engineered in Azure to track cumulative compute runtime hours, prevent budget overruns across development pools, and enforce resource allocation caps via serverless deallocation.

---

## Architecture Overview

The system addresses cloud compute overspending in research and lab environments by continuously monitoring compute usage, maintaining state persistence across execution cycles, and automating policy enforcement.

```text
  ┌────────────────────────────────────────────────────────┐
  │         Azure Automation (Hourly Scheduled Runbook)     │
  │         • Python 3.10 Runtime Environment              │
  │         • System-Assigned Managed Identity Authentication │
  └───────────────────────────┬────────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
┌──────────────────────────────┐ ┌────────────────────────────────┐
│ Azure Monitor Metrics API    │ │ Azure Blob Storage             │
│ • Delta query: PT1M samples  │ │ • Container: vm-monitoring     │
│ • Metric: VmAvailability     │ │ • State: vm_usage_state.json   │
└──────────────┬───────────────┘ └────────────────┬───────────────┘
               │                                  │
               └──────────────┬───────────────────┘
                              ▼
           ┌─────────────────────────────────────┐
           │ Cumulative Usage & Quota Logic      │
           │ • Total = Baseline + Σ(Deltas)      │
           └──────────────────┬──────────────────┘
                              │
         ┌────────────────────┴────────────────────┐
         ▼ [Usage >= 175h]                         ▼ [Usage >= 200h]
┌──────────────────────────────┐         ┌────────────────────────┐
│ Logic App Webhook Trigger    │         │ Azure Compute API      │
│ • HTML usage tables          │         │ • VM begin_deallocate  │
│ • Office 365 dispatch        │         │ • Stops compute billing│
└──────────────────────────────┘         └────────────────────────┘
```
### Key Engineering Highlights

* **Stateful Serverless Pattern:** Azure Automation Runbooks execute statelessly. To bypass the strict 30-day data retention window of the Azure Monitor Metrics API, the engine persists cumulative usage states in Azure Blob Storage (`vm_usage_state.json`), enabling indefinite tracking without external SQL database overhead.
  
* **Delta Query Execution:** Instead of scanning large temporal windows, each run calculates discrete active minutes since the last checkpoint (`last_run_utc`), mitigating API throttling and query latency.
* **Zero-Trust & Least Privilege (RBAC):** Completely eliminates hardcoded passwords, tokens, or service principal secrets. Authentication is fully brokered by Azure Managed Identity scoped to:
  * `Contributor` on the target Compute Resource Group.
  * `Storage Blob Data Contributor` on the storage account layer.
* **Automated Guardrails & FinOps Enforcement:**
  * **Warning State (175 Hours):** Triggers proactive alerts before resources hit operational ceilings.
  * **Quota Cap (200 Hours):** Automatically triggers `begin_deallocate` against compute instances, halting hourly billing immediately.
* **Automated CI/CD Quality Pipeline:** Integrated with GitHub Actions to enforce syntax compliance, structural linting, and dependency validation on every push.

---

---

## Tech Stack & SDKs

* **Cloud Platform:** Microsoft Azure (Automation Accounts, Logic Apps, Blob Storage, Azure Monitor)
* **Language & Runtime:** Python 3.10
* **Azure SDKs:** `azure-identity`, `azure-mgmt-compute`, `azure-mgmt-monitor`, `azure-storage-blob`
* **CI/CD:** GitHub Actions (Ubuntu / Flake8 Linting)

---

## Repository Structure

```text
azure-finops-runtime-enforcer/
├── .github/
│   └── workflows/
│       └── code-quality.yml    # Automated CI syntax & linting pipeline
├── src/
│   ├── enforce_vm_runtime.py   # Core monitoring and deallocation engine
│   └── weekly_vm_report.py     # HTML report compiler and Logic App dispatcher
├── requirements.txt            # Python dependencies
└── README.md                   # System documentation
