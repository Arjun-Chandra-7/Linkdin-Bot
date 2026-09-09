"""Runtime settings, editable from the app."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.schemas import SettingsOut, SettingsUpdate
from app.core.errors import ValidationError
from app.core.settings_store import DEFAULTS, all_settings, update_settings
from app.database.models import Device
from app.database.session import get_db
from app.security.auth import get_current_device

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def read_settings(
    db: Session = Depends(get_db), _: Device = Depends(get_current_device)
) -> SettingsOut:
    return SettingsOut(values=all_settings(db))


@router.get("/schema")
def settings_schema(_: Device = Depends(get_current_device)) -> dict:
    """Default values, so the app can render editors without hard-coding them."""
    return {"defaults": DEFAULTS, "keys": sorted(DEFAULTS)}


@router.put("", response_model=SettingsOut)
def write_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    _: Device = Depends(get_current_device),
) -> SettingsOut:
    try:
        values = update_settings(db, payload.values)
    except KeyError as exc:
        raise ValidationError(
            f"Unknown setting: {exc.args[0]}",
            details={"allowed": sorted(DEFAULTS)},
        ) from exc
    db.commit()
    return SettingsOut(values=values)
