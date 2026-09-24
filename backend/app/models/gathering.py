from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .mixins import IDMixin


class GatheringRequest(IDMixin, Base):
    __tablename__ = "gathering_requests"

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    access_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_key_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)
    access_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sheet_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="sent", nullable=False)
    company_website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_tools: Mapped[str | None] = mapped_column(Text, nullable=True)
    pain_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_sheet_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GatheringServerDetail(IDMixin, Base):
    __tablename__ = "gathering_server_details"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gathering_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("gathering_requests.id"), nullable=True, index=True
    )
    server_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provisioned_storage_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_system: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_virtual: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hypervisor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cpu_string: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sql_edition: Mapped[str | None] = mapped_column(String(255), nullable=True)
    application: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cpu_utilization_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_utilization_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_in_use: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GatheringFileNasDetail(IDMixin, Base):
    __tablename__ = "gathering_file_nas_details"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gathering_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("gathering_requests.id"), nullable=True, index=True
    )
    file_server_share_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_used_capacity_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    access_protocol: Mapped[str | None] = mapped_column(String(80), nullable=True)
    total_provisioned_capacity_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_efficiency_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_iops: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_throughput_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_iops: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_throughput_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_pool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    array_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    array_vendor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    average_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    application: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GatheringBlockStorageDetail(IDMixin, Base):
    __tablename__ = "gathering_block_storage_details"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gathering_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("gathering_requests.id"), nullable=True, index=True
    )
    volume_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_used_capacity_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_provisioned_capacity_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_iops: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_throughput_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_iops: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_throughput_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    array_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    average_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    application: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)