import os
import json
import requests
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# Configuration (Generic & Sanitized)
STORAGE_ACCOUNT_NAME = os.getenv("STORAGE_ACCOUNT_NAME", "devfinopsstorage")
CONTAINER_NAME = os.getenv("STORAGE_CONTAINER_NAME", "vm-monitoring-state")
BLOB_NAME = os.getenv("STORAGE_BLOB_NAME", "vm_usage_state.json")

# Fallback placeholder for Logic App Webhook endpoint
LOGIC_APP_URL = os.getenv(
    "LOGIC_APP_WEBHOOK_URL",
    "https://prod-xx.westeurope.logic.azure.com:443/workflows/<WORKFLOW_ID>/triggers/manual/paths/invoke?api-version=2016-10-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=<SIGNATURE>"
)

# Generic email recipients (separated by semicolon for Office 365 Connector)
EMAIL_RECIPIENTS = os.getenv(
    "ALERT_RECIPIENTS",
    "cloud-admin@example.com; devops-lead@example.com; finance-auditor@example.com"
)


def load_state_from_blob():
    """Fetches the latest VM usage state JSON from Azure Blob Storage."""
    try:
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(
            account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net",
            credential=credential
        )
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)
        download_stream = blob_client.download_blob()
        return json.loads(download_stream.readall())
    except Exception as e:
        print(f"Error reading state from blob: {e}")
        return {}


def generate_html_report(state_data):
    """Generates an HTML table summarizing VM usage."""
    # Extract the VMs dictionary safely
    vms_dict = state_data.get("vms", state_data)
    
    rows_html = ""
    sorted_vms = sorted(vms_dict.keys())
    
    for vm_name in sorted_vms:
        item = vms_dict[vm_name]
        
        # Safe extraction of cumulative hours
        if isinstance(item, dict):
            hours = item.get("total_hours", item.get("current_hours", item.get("hours", 0)))
        else:
            try:
                hours = float(item)
            except (ValueError, TypeError):
                hours = 0.0
        
        # Status styling thresholds
        if hours >= 200:
            status_style = "color: #d9534f; font-weight: bold;"
            status_text = "חריגה (200h+)"
        elif hours >= 175:
            status_style = "color: #f0ad4e; font-weight: bold;"
            status_text = "אזהרה (175h+)"
        else:
            status_style = "color: #5cb85c;"
            status_text = "תקין"

        rows_html += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{vm_name}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{hours:.1f} שעות</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center; {status_style}">{status_text}</td>
        </tr>
        """

    html_content = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 650px; margin: auto;">
        <h2 style="color: #003366;">דוח ניצול שעות שבועי - מכונות וירטואליות (Compute Pool)</h2>
        <p>שלום רב,</p>
        <p>להלן סיכום שעות הפעילות המצטברות עבור סביבות החישוב והפיתוח נכון להיום:</p>
        
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <thead>
                <tr style="background-color: #003366; color: white;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: right;">שם המכונה</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">שעות פעילות</th>
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: center;">סטטוס</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <br>
        <p style="font-size: 0.9em; color: #666;">הודעה זו הופקה באופן אוטומטי על ידי מערכת הניטור בענן (Azure Serverless).</p>
    </div>
    """
    return html_content


def main():
    print("Fetching VM state...")
    state_data = load_state_from_blob()
    
    if not state_data:
        print("No VM state data found.")
        return

    print("Generating HTML report...")
    report_html = generate_html_report(state_data)

    payload = {
        "event_type": "Weekly Report",
        "vm_name": "Compute Pool Summary",
        "current_hours": 0,
        "recipients": EMAIL_RECIPIENTS,
        "message": report_html
    }

    print("Sending report to Logic App...")
    try:
        res = requests.post(LOGIC_APP_URL, json=payload, timeout=15)
        res.raise_for_status()
        print("Weekly report email sent successfully!")
    except Exception as e:
        print(f"Failed to send weekly report: {e}")


if __name__ == "__main__":
    main()
