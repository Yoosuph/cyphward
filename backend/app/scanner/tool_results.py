"""Preserve per-host tool coverage separately from observations/findings."""
import asyncio
from typing import Any


class ToolExecutionError(RuntimeError):
    """A tool did not finish an assessment; an empty result is not clean proof."""


class ToolBatchResult(list):
    """List-compatible observations with explicit successful and failed targets."""

    def __init__(self, observations, attempted_hosts, successful_hosts, failed_hosts):
        super().__init__(observations)
        self.attempted_hosts = list(attempted_hosts)
        self.successful_hosts = list(successful_hosts)
        self.failed_hosts = dict(failed_hosts)

    def coverage(self) -> dict[str, Any]:
        return {
            "attempted_hosts": self.attempted_hosts,
            "successful_hosts": self.successful_hosts,
            "failed_hosts": self.failed_hosts,
        }

    def progress(self) -> dict[str, Any]:
        status = "failed" if self.failed_hosts else "completed" if self.attempted_hosts else "skipped"
        result = {
            "status": status,
            "targets_attempted": len(self.attempted_hosts),
            "targets_succeeded": len(self.successful_hosts),
            "targets_failed": len(self.failed_hosts),
        }
        if self.failed_hosts:
            result["error"] = f"{len(self.failed_hosts)} of {len(self.attempted_hosts)} targets could not be assessed."
        return result


def collect_tool_results(hostnames, results) -> ToolBatchResult:
    observations, successful, failed = [], [], {}
    for host, result in zip(hostnames, results):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, list):
            observations.extend(result)
            successful.append(host)
        elif isinstance(result, dict):
            observations.append(result)
            successful.append(host)
        else:
            failed[host] = str(result or "No usable assessment returned")[:300]
    return ToolBatchResult(observations, hostnames, successful, failed)
