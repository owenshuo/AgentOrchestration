"""Agent Registry — Manages agent lifecycle and metadata."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._plugin_index: Dict[str, List[str]] = {}
        self._resolution_cache: Dict[
            Tuple[str, Tuple[Tuple[str, str], ...]],
            List[str],
        ] = {}
        self.audit_records: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        config = config or {}
        plugin_config = self._normalize_plugin_config(agent_type, config)
        plugin_name, plugin_version, dependencies = plugin_config
        self._validate_plugin_dependencies(
            plugin_name,
            plugin_version,
            dependencies,
        )

        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config,
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "plugin": {
                "name": plugin_name,
                "version": plugin_version,
                "dependencies": dependencies,
            },
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        self._plugin_index.setdefault(plugin_name, []).append(agent_id)
        self._invalidate_resolution_cache("plugin_registered", plugin_name)
        self._record_audit(
            "plugin_registered",
            "accepted",
            plugin_name=plugin_name,
            plugin_version=plugin_version,
        )
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        self._invalidate_resolution_cache("status_changed", agent_id)
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        plugin_name = agent["plugin"]["name"]
        if (
            plugin_name in self._plugin_index
            and agent_id in self._plugin_index[plugin_name]
        ):
            self._plugin_index[plugin_name].remove(agent_id)
        self._invalidate_resolution_cache("plugin_deleted", plugin_name)
        return True

    def count(self) -> int:
        return len(self._agents)

    def resolve_handlers(
        self,
        agent_type: str,
        required_plugins: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        dependencies = self._normalize_dependencies(required_plugins or {})
        cache_key = (agent_type, tuple(sorted(dependencies.items())))
        cached_ids = self._resolution_cache.get(cache_key)
        if cached_ids is not None:
            return [
                self._agents[agent_id]
                for agent_id in cached_ids
                if agent_id in self._agents
            ]

        handlers = []
        for agent in self._agents.values():
            if agent["type"] != agent_type:
                continue
            if not self._agent_can_resolve(agent, dependencies):
                continue
            handlers.append(agent)

        self._resolution_cache[cache_key] = [agent["id"] for agent in handlers]
        self._record_audit(
            "plugin_dependency_resolution",
            "accepted",
            agent_type=agent_type,
            handler_count=len(handlers),
        )
        return list(handlers)

    def _normalize_plugin_config(
        self,
        agent_type: str,
        config: Dict[str, Any],
    ) -> Tuple[str, str, Dict[str, str]]:
        plugin = config.get("plugin") or {}
        plugin_name = (
            config.get("plugin_name")
            or plugin.get("name")
            or agent_type
        )
        plugin_version = (
            config.get("plugin_version")
            or plugin.get("version")
            or "1.0.0"
        )
        dependencies = (
            config.get("plugin_dependencies")
            or config.get("dependencies")
            or plugin.get("dependencies")
            or {}
        )
        if not isinstance(plugin_name, str) or not plugin_name.strip():
            raise ValueError("plugin name is required")
        if not isinstance(plugin_version, str) or not plugin_version.strip():
            raise ValueError("plugin version is required")
        self._parse_version(plugin_version)
        return (
            plugin_name.strip(),
            plugin_version.strip(),
            self._normalize_dependencies(dependencies),
        )

    def _normalize_dependencies(self, dependencies: Any) -> Dict[str, str]:
        if isinstance(dependencies, dict):
            items = dependencies.items()
        elif isinstance(dependencies, list):
            items = [
                (dep.get("name"), dep.get("version"))
                for dep in dependencies
                if isinstance(dep, dict)
            ]
        else:
            raise ValueError("plugin dependencies must be a mapping or list")

        normalized: Dict[str, str] = {}
        for name, constraint in items:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("dependency name is required")
            if not isinstance(constraint, str) or not constraint.strip():
                raise ValueError("dependency version constraint is required")
            self._validate_constraint(constraint)
            normalized[name.strip()] = constraint.strip()
        return normalized

    def _validate_plugin_dependencies(
        self,
        plugin_name: str,
        plugin_version: str,
        dependencies: Dict[str, str],
    ) -> None:
        missing = [
            name
            for name, constraint in dependencies.items()
            if not self._dependency_is_satisfied(name, constraint)
        ]
        if not missing:
            return

        self._record_audit(
            "plugin_dependency_resolution",
            "rejected",
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            missing_dependencies=missing,
        )
        raise ValueError("plugin dependency versions are not satisfied")

    def _agent_can_resolve(
        self,
        agent: Dict[str, Any],
        required_plugins: Dict[str, str],
    ) -> bool:
        if self._plugin_is_unavailable(agent):
            self._record_audit(
                "plugin_dependency_resolution",
                "deferred",
                agent_id=agent["id"],
                reason="handler_not_active",
            )
            return False

        plugin = agent["plugin"]
        dependencies = dict(plugin["dependencies"])
        dependencies.update(required_plugins)
        missing = [
            name
            for name, constraint in dependencies.items()
            if not self._dependency_is_satisfied(name, constraint)
        ]
        if not missing:
            return True

        self._record_audit(
            "plugin_dependency_resolution",
            "deferred",
            agent_id=agent["id"],
            missing_dependencies=missing,
        )
        return False

    def _dependency_is_satisfied(self, name: str, constraint: str) -> bool:
        for agent_id in self._plugin_index.get(name, []):
            agent = self._agents.get(agent_id)
            if not agent:
                continue
            if self._plugin_is_unavailable(agent):
                continue
            version = agent["plugin"]["version"]
            if self._version_satisfies(version, constraint):
                return True
        return False

    def _plugin_is_unavailable(self, agent: Dict[str, Any]) -> bool:
        unavailable_statuses = {
            AgentStatus.PAUSED.value,
            AgentStatus.STOPPED.value,
            AgentStatus.FAILED.value,
            AgentStatus.TERMINATED.value,
        }
        return agent["status"] in unavailable_statuses

    def _validate_constraint(self, constraint: str) -> None:
        for part in constraint.split(","):
            self._parse_constraint_part(part.strip())

    def _version_satisfies(self, version: str, constraint: str) -> bool:
        parsed_version = self._parse_version(version)
        for part in constraint.split(","):
            operator, expected = self._parse_constraint_part(part.strip())
            parsed_expected = self._parse_version(expected)
            if operator == "==" and parsed_version != parsed_expected:
                return False
            if operator == ">=" and parsed_version < parsed_expected:
                return False
            if operator == ">" and parsed_version <= parsed_expected:
                return False
            if operator == "<=" and parsed_version > parsed_expected:
                return False
            if operator == "<" and parsed_version >= parsed_expected:
                return False
        return True

    def _parse_constraint_part(self, part: str) -> Tuple[str, str]:
        for operator in (">=", "<=", "==", ">", "<"):
            if part.startswith(operator):
                version = part[len(operator):].strip()
                self._parse_version(version)
                return operator, version
        self._parse_version(part)
        return "==", part

    def _parse_version(self, version: str) -> Tuple[int, int, int]:
        parts = version.split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise ValueError("plugin versions must use major.minor.patch")
        return int(parts[0]), int(parts[1]), int(parts[2])

    def _invalidate_resolution_cache(self, reason: str, subject: str) -> None:
        self._resolution_cache.clear()
        self._record_audit(
            "plugin_resolution_cache_invalidated",
            "accepted",
            reason=reason,
            subject=subject,
        )

    def _record_audit(
        self,
        event: str,
        decision: str,
        **fields: Any,
    ) -> None:
        safe_fields = {
            key: value
            for key, value in fields.items()
            if key not in {"config", "env", "payload", "secret", "token"}
        }
        self.audit_records.append(
            {
                "event": event,
                "decision": decision,
                "timestamp": time.time(),
                **safe_fields,
            }
        )

# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update
