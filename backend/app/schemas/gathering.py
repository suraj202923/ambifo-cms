from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GatheringRequestCreate(BaseModel):
    customer_id: int
    note: str | None = None
    expires_days: int = 14
    access_key: str | None = None
    send_email: bool = True


class GatheringVerifyIn(BaseModel):
    access_key: str


class ServerDetailIn(BaseModel):
    server_name: str
    cpu_cores: int | None = None
    memory_mb: int | None = None
    provisioned_storage_gb: float | None = None
    operating_system: str | None = None
    is_virtual: bool | None = None
    hypervisor_name: str | None = None
    cpu_string: str | None = None
    environment: str | None = None
    sql_edition: str | None = None
    application: str | None = None
    cpu_utilization_peak: float | None = None
    memory_utilization_peak: float | None = None
    time_in_use: float | None = None
    annual_cost_usd: float | None = None
    storage_type: str | None = None


class BlockStorageDetailIn(BaseModel):
    volume_name: str
    total_used_capacity_gb: float | None = None
    total_provisioned_capacity_gb: float | None = None
    peak_iops: float | None = None
    peak_throughput_mbps: float | None = None
    average_iops: float | None = None
    average_throughput_mbps: float | None = None
    array_name: str | None = None
    average_latency_ms: float | None = None
    application: str | None = None


class FileNasDetailIn(BaseModel):
    file_server_share_name: str
    total_used_capacity_gb: float | None = None
    access_protocol: str | None = None
    total_provisioned_capacity_gb: float | None = None
    storage_efficiency_ratio: float | None = None
    peak_iops: float | None = None
    peak_throughput_mbps: float | None = None
    average_iops: float | None = None
    average_throughput_mbps: float | None = None
    storage_pool_name: str | None = None
    array_name: str | None = None
    array_vendor: str | None = None
    average_latency_ms: float | None = None
    application: str | None = None


class GatheringSubmitIn(BaseModel):
    company_website: str | None = None
    current_tools: str | None = None
    pain_points: str | None = None
    servers: list[ServerDetailIn] = []
    block_storage: list[BlockStorageDetailIn] = []
    file_nas: list[FileNasDetailIn] = []


class GatheringRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    customer_id: int
    customer_name: str | None = None
    note: str | None = None
    expires_at: datetime | None = None
    access_key_hint: str | None = None
    access_verified_at: datetime | None = None
    status: str
    company_website: str | None = None
    current_tools: str | None = None
    pain_points: str | None = None
    submitted_at: datetime | None = None
    submitted_sheet_path: str | None = None
    is_locked: bool
    locked_at: datetime | None = None
    locked_by: str | None = None
    created_at: datetime

    server_count: int = 0
    block_count: int = 0
    file_count: int = 0


class ServerDetailOut(ServerDetailIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    gathering_request_id: int | None = None


class BlockStorageDetailOut(BlockStorageDetailIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    gathering_request_id: int | None = None


class FileNasDetailOut(FileNasDetailIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    gathering_request_id: int | None = None


class GatheringDetailOut(GatheringRequestOut):
    servers: list[ServerDetailOut] = []
    block_storage: list[BlockStorageDetailOut] = []
    file_nas: list[FileNasDetailOut] = []


class GatheringPublicOut(BaseModel):
    customer_id: int
    note: str | None = None
    expires_at: datetime | None = None
    access_key_hint: str | None = None
    access_verified_at: datetime | None = None
    is_locked: bool
    status: str


class GatheringSubmitResult(BaseModel):
    ok: bool
    status: str
    submitted_at: datetime | None = None
    message: str = "submitted"