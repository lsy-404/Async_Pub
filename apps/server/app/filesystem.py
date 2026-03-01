import sys
from pathlib import Path
from typing import Any, Optional, Dict, Union
from pydantic import BaseModel, Field

# Python 3.11+ has tomllib built-in, 3.10 needs tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

class SidebarSession(BaseModel):
    id: Union[int, str]
    name: str
    type: str = "session"

class SidebarFolder(BaseModel):
    id: Union[int, str]
    name: str
    type: str = "folder"
    children: list[SidebarSession] = Field(default_factory=list)

class SidebarProject(BaseModel):
    id: Union[int, str]
    name: str
    items: list[SidebarSession | SidebarFolder] = Field(default_factory=list)

class SidebarStructure(BaseModel):
    projects: list[SidebarProject] = Field(default_factory=list)

class DatabaseManager:
    def __init__(self, data_path: Path):
        self.data_path = data_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not self.data_path.exists():
            default_structure = {
                "projects": [
                    {
                        "id": "default-project",
                        "name": "My Workspace",
                        "items": []
                    }
                ]
            }
            # Initialize with empty sessions map
            full_data = {
                "sidebar": default_structure,
                "sessions": {}
            }
            self._save_raw(full_data)

    def _load_raw(self) -> Dict[str, Any]:
        if not self.data_path.exists():
            return {"sidebar": {"projects": []}, "sessions": {}}
        with open(self.data_path, "rb") as f:
            return tomllib.load(f)

    def _save_raw(self, data: Dict[str, Any]):
        with open(self.data_path, "wb") as f:
            tomli_w.dump(data, f)

    def get_structure(self) -> SidebarStructure:
        data = self._load_raw()
        sidebar_data = data.get("sidebar", {"projects": []})
        return SidebarStructure(**sidebar_data)

    def save_structure(self, structure: SidebarStructure):
        data = self._load_raw()
        data["sidebar"] = structure.model_dump()
        self._save_raw(data)

    def get_session_metadata(self, session_id: str) -> Dict[str, Any]:
        data = self._load_raw()
        return data.get("sessions", {}).get(session_id, {})

    def save_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        data = self._load_raw()
        if "sessions" not in data:
            data["sessions"] = {}
        data["sessions"][session_id] = metadata
        self._save_raw(data)

    def delete_session_metadata(self, session_id: str):
        data = self._load_raw()
        if "sessions" in data and session_id in data["sessions"]:
            del data["sessions"][session_id]
            self._save_raw(data)
