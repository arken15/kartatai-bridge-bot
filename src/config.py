from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


DEFAULT_ADMIN_USER_IDS = (8708949561, 7573475844, 7741029169)


def merge_admin_ids(owner_user_id: int | None, extra: list[int]) -> list[int]:
    result: list[int] = []
    for user_id in (*DEFAULT_ADMIN_USER_IDS, *extra):
        if user_id not in result:
            result.append(user_id)
    if owner_user_id is not None and owner_user_id not in result:
        result.append(owner_user_id)
    return result


def _parse_int_list(raw: str | None) -> list[int]:
    if not raw or not raw.strip():
        return []
    result: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk:
            result.append(int(chunk))
    return result


@dataclass(frozen=True)
class CriteriaField:
    key: str
    prompt: str
    type: str = "text"
    optional: bool = False
    skip_values: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FlowConfig:
    navigation: list[list[str]]
    criteria: list[CriteriaField]


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str
    client_bot_token: str
    team_bot_username: str
    allowed_user_ids: list[int]
    owner_user_id: int | None
    admin_user_ids: list[int]
    session_name: str
    flow: FlowConfig
    data_dir: Path
    session_dir: Path
    session_path: Path
    flow_path: Path


def load_flow_config(path: Path) -> FlowConfig:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    criteria = [
        CriteriaField(
            key=item["key"],
            prompt=item["prompt"],
            type=item.get("type", "text"),
            optional=bool(item.get("optional", False)),
            skip_values=[str(v).lower() for v in item.get("skip_values", [])],
        )
        for item in raw.get("criteria", [])
    ]

    return FlowConfig(
        navigation=[list(step) for step in raw.get("navigation", [])],
        criteria=criteria,
    )


def load_settings() -> Settings:
    flow_path = ROOT_DIR / "config" / "flow.yaml"
    session_name = os.getenv("SESSION_NAME", "kartatai_userbot")
    data_dir = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
    session_dir = Path(os.getenv("SESSION_DIR", str(data_dir / "sessions")))

    owner_raw = os.getenv("OWNER_USER_ID", "").strip()
    owner_user_id = int(owner_raw) if owner_raw else None

    local_session = ROOT_DIR / session_name
    session_path = local_session if local_session.with_suffix(".session").exists() else session_dir / session_name

    return Settings(
        api_id=int(os.environ["TELEGRAM_API_ID"]),
        api_hash=os.environ["TELEGRAM_API_HASH"],
        phone=os.environ["TELEGRAM_PHONE"],
        client_bot_token=os.environ["CLIENT_BOT_TOKEN"],
        team_bot_username=os.environ.get("TEAM_BOT_USERNAME", "KartataiFuturaBot"),
        allowed_user_ids=_parse_int_list(os.getenv("ALLOWED_USER_IDS")),
        owner_user_id=owner_user_id,
        admin_user_ids=merge_admin_ids(
            owner_user_id,
            _parse_int_list(os.getenv("ADMIN_USER_IDS")),
        ),
        session_name=session_name,
        flow=load_flow_config(flow_path),
        data_dir=data_dir,
        session_dir=session_dir,
        session_path=session_path,
        flow_path=flow_path,
    )
