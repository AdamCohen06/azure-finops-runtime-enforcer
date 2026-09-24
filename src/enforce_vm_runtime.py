import os
import json
import time
from datetime import datetime, timedelta, timezone
from azure.identity import ManagedIdentityCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.storage.blob import BlobServiceClient

# Configuration (Generic & Sanitized)
SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")
RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "devops-compute-rg")
STORAGE_ACCOUNT_NAME = os.getenv("STORAGE_ACCOUNT_NAME", "devfinopsstorage")
CONTAINER_NAME = os.getenv("STORAGE_CONTAINER_NAME", "vm-monitoring-state")
STATE_BLOB_NAME = os.getenv("STORAGE_BLOB_NAME", "vm_usage_state.json")

# Quota Thresholds
WARNING_HOURS_LIMIT = 175.0  # Early warning threshold
MAX_HOURS_LIMIT = 200.0      # Deallocation threshold

# SAFETY TOGGLE:
# Set DRY_RUN = True to test logic without deallocating machines.
# Set DRY_RUN = False to enable active production deallocation.
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "t")

# Target Virtual Machines pool
VM_PREFIX = os.getenv("VM_PREFIX", "dev-worker-")
VM_LIST = [f"{VM_PREFIX}{i}" for i in range(1, 17)]


def get_azure_clients():
    """Initializes Azure SDK management clients using Managed Identity."""
    credential = ManagedIdentityCredential()
    compute_client = ComputeManagementClient(credential, SUBSCRIPTION_ID)
    monitor_client = MonitorManagementClient(credential, SUBSCRIPTION_ID)
    
    blob_service_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    blob_service_client = BlobServiceClient(account_url=blob_service_url, credential=credential)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)
    
    return compute_client, monitor_client, container_client


def load_state(container_client):
    """Retrieves current execution state from Azure Blob Storage."""
    try:
        blob_client = container_client.get_blob_client(STATE_BLOB_NAME)
        download_stream = blob_client.download_blob()
        return json.loads(download_stream.readall())
    except Exception as e:
        print(f"⚠️ Error loading state from Blob Storage: {e}")
        return {}


def save_state(container_client, state_data):
    """Persists updated state back to Azure Blob Storage."""
    try:
        blob_client = container_client.get_blob_client(STATE_BLOB_NAME)
        blob_client.upload_blob(json.dumps(state_data, indent=4), overwrite=True)
        print("✅ State successfully updated and saved to Azure Blob Storage!")
    except Exception as e:
        print(f"❌ Error saving state to Blob Storage: {e}")


def get_vm_active_hours_delta(monitor_client, vm_name, last_checked_time, now_utc):
    """Queries Azure Monitor API for active compute minutes and calculates delta hours."""
    start_str = last_checked_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    timespan = f"{start_str}/{end_str}"
    
    vm_resource_id = (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/"
        f"providers/Microsoft.Compute/virtualMachines/{vm_name}"
    )
    
    try:
        metrics_data = monitor_client.metrics.list(
            resource_uri=vm_resource_id,
            timespan=timespan,
            interval='PT1M',
            metricnames='VmAvailabilityMetric',
            aggregation='Average'
        )
        active_minutes = 0
        for item in metrics_data.value:
            for timeseries in item.timeseries:
                for data_point in timeseries.data:
                    if data_point.average is not None and data_point.average > 0:
                        active_minutes += 1
        return active_minutes / 60.0
    except Exception as e:
        print(f"❌ Failed to fetch metrics for {vm_name}: {e}")
        return 0.0


def main():
    compute_client, monitor_client, container_client = get_azure_clients()
    state = load_state(container_client)
    now_utc = datetime.now(timezone.utc)
    
    print(f"--- Checking VM usage since ({state.get('last_run_utc', 'N/A')}) ---")
    print(f"🛡️ Mode: {'DRY RUN (SAFE MODE)' if DRY_RUN else 'LIVE ENFORCEMENT'}\n")
    
    last_run_str = state.get("last_run_utc")
    if last_run_str:
        last_run_time = datetime.fromisoformat(last_run_str)
    else:
        last_run_time = now_utc - timedelta(hours=1)
        
    time_diff_seconds = (now_utc - last_run_time).total_seconds()
    if time_diff_seconds < 60:
        print(f"ℹ️ Skipping query: Time since last check is under 1 minute ({int(time_diff_seconds)}s).")
        return

    if "vms" not in state:
        state["vms"] = {}

    for vm_name in VM_LIST:
        current_vm_data = state["vms"].get(vm_name, {})
        if isinstance(current_vm_data, dict):
            previous_total = current_vm_data.get("total_hours", 0.0)
        else:
            previous_total = float(current_vm_data)
        
        delta_hours = get_vm_active_hours_delta(monitor_client, vm_name, last_run_time, now_utc)
        new_total = previous_total + delta_hours
        
        state["vms"][vm_name] = {"total_hours": round(new_total, 2)}
        
        if WARNING_HOURS_LIMIT <= new_total < MAX_HOURS_LIMIT:
            print(f"⚠️ [WARNING] {vm_name}: {new_total:.2f}h total (+{delta_hours:.1f}h new) - Approaching cap!")
        elif new_total >= MAX_HOURS_LIMIT:
            print(f"🚨 [CAP EXCEEDED] {vm_name}: {new_total:.2f}h total (+{delta_hours:.1f}h new) - Cap reached!")
            if not DRY_RUN:
                print(f"🛑 [ACTION] Deallocating {vm_name}...")
                compute_client.virtual_machines.begin_deallocate(RESOURCE_GROUP, vm_name)
            else:
                print(f"🔍 [DRY RUN] Would deallocate {vm_name}.")
        else:
            print(f"🟢 [OK] {vm_name}: {new_total:.2f}h total (+{delta_hours:.1f}h new)")
            
        time.sleep(1)

    state["last_run_utc"] = now_utc.isoformat()
    save_state(container_client, state)


if __name__ == "__main__":
    main()
