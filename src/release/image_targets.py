"""Container image target validation for release pushes."""

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Set

TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
REGISTRY_PATTERN = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?$")
PATH_PART_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class ReleaseTargetError(ValueError):
    """Raised when a release image target is not approved for push."""


@dataclass(frozen=True)
class ReleaseImageTarget:
    registry: str
    namespace: str
    image: str
    tag: str

    @property
    def approved_namespace(self) -> str:
        return f"{self.registry}/{self.namespace}"

    @property
    def reference(self) -> str:
        return f"{self.approved_namespace}/{self.image}:{self.tag}"

    @classmethod
    def parse(cls, reference: str) -> "ReleaseImageTarget":
        try:
            before_tag, tag = reference.rsplit(":", 1)
            registry, namespace, image = before_tag.split("/", 2)
        except ValueError as exc:
            raise ReleaseTargetError(
                "image reference must be registry/namespace/image:tag"
            ) from exc

        return cls(
            registry=registry,
            namespace=namespace,
            image=image,
            tag=tag,
        )


class ReleaseTargetValidator:
    def __init__(self, allowed_namespaces: Iterable[str]):
        self.allowed_namespaces: Set[str] = {
            namespace.strip()
            for namespace in allowed_namespaces
            if namespace and namespace.strip()
        }

    def validate_before_push(
        self,
        target: ReleaseImageTarget,
    ) -> Dict[str, str]:
        self._validate_tag(target.tag)
        self._validate_registry(target.registry)
        self._validate_path_part(target.namespace, "registry namespace")
        self._validate_image_path(target.image)
        self._validate_allowlist(target)
        return {
            "registry": target.registry,
            "namespace": target.namespace,
            "image": target.image,
            "tag": target.tag,
            "approved_target": target.reference,
        }

    def _validate_tag(self, tag: str) -> None:
        if not TAG_PATTERN.fullmatch(tag):
            raise ReleaseTargetError("invalid image tag")

    def _validate_registry(self, registry: str) -> None:
        if not REGISTRY_PATTERN.fullmatch(registry):
            raise ReleaseTargetError("invalid registry host")

    def _validate_image_path(self, image: str) -> None:
        parts = image.split("/")
        if not parts or any(not part for part in parts):
            raise ReleaseTargetError("invalid image name")
        for part in parts:
            self._validate_path_part(part, "image name")

    def _validate_path_part(self, value: str, label: str) -> None:
        if not PATH_PART_PATTERN.fullmatch(value):
            raise ReleaseTargetError(f"invalid {label}")

    def _validate_allowlist(self, target: ReleaseImageTarget) -> None:
        if target.approved_namespace not in self.allowed_namespaces:
            raise ReleaseTargetError("unapproved registry namespace")
