from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass

import paramiko
from mcp.server.fastmcp import Context, FastMCP


@dataclass(frozen=True)
class SSHConfig:
    host: str
    username: str
    port: int
    private_key_path: str
    private_key_passphrase: str | None
    strict_host_key_checking: bool
    known_hosts_path: str | None


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _require_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer: {value}") from exc


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean: {value}")


def _load_config() -> SSHConfig:
    host = _require_env("SSH_HOST")
    username = _require_env("SSH_USER")
    port = _parse_int(_env("SSH_PORT"), 22)
    private_key_path = _require_env("SSH_PRIVATE_KEY_PATH")
    private_key_passphrase = _env("SSH_PRIVATE_KEY_PASSPHRASE")
    strict_host_key_checking = _parse_bool(_env("SSH_STRICT_HOST_KEY_CHECKING"), False)
    known_hosts_path = _env("SSH_KNOWN_HOSTS_PATH")

    if (
        strict_host_key_checking
        and known_hosts_path
        and not os.path.exists(known_hosts_path)
    ):
        raise RuntimeError(
            f"SSH_KNOWN_HOSTS_PATH does not exist: {known_hosts_path}. "
            "Prime known_hosts first (for Windows: run vericase/ops/setup-ssh.ps1)."
        )

    return SSHConfig(
        host=host,
        username=username,
        port=port,
        private_key_path=private_key_path,
        private_key_passphrase=private_key_passphrase,
        strict_host_key_checking=strict_host_key_checking,
        known_hosts_path=known_hosts_path,
    )


def _run_ssh_command(cfg: SSHConfig, command: str, timeout_s: float) -> dict:
    client = paramiko.SSHClient()

    if cfg.strict_host_key_checking:
        client.load_system_host_keys()
        if cfg.known_hosts_path:
            client.load_host_keys(cfg.known_hosts_path)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    client.connect(
        hostname=cfg.host,
        port=cfg.port,
        username=cfg.username,
        key_filename=cfg.private_key_path,
        passphrase=cfg.private_key_passphrase,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout_s,
        banner_timeout=timeout_s,
        auth_timeout=timeout_s,
    )

    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_s)
        _ = stdin  # unused
        out_text = stdout.read().decode("utf-8", errors="replace")
        err_text = stderr.read().decode("utf-8", errors="replace")
        exit_status = stdout.channel.recv_exit_status()
        return {
            "host": cfg.host,
            "username": cfg.username,
            "port": cfg.port,
            "command": command,
            "exit_status": exit_status,
            "stdout": out_text,
            "stderr": err_text,
        }
    finally:
        client.close()


mcp = FastMCP(
    name="SSH",
    instructions=(
        "Run commands on a remote host over SSH. "
        "Configure SSH_HOST, SSH_USER, SSH_PORT (optional), SSH_PRIVATE_KEY_PATH, "
        "SSH_PRIVATE_KEY_PASSPHRASE (optional), and SSH_STRICT_HOST_KEY_CHECKING (optional). "
        "Optionally set SSH_KNOWN_HOSTS_PATH to a known_hosts file path when strict checking is enabled."
    ),
)


@mcp.tool()
async def ssh_run(ctx: Context, command: str, timeout_s: float = 30.0) -> dict:
    """Run a command via SSH and return stdout/stderr/exit status."""

    _ = ctx  # reserved for future enhancements

    cfg = _load_config()
    if not command or not command.strip():
        raise ValueError("command is required")

    result = await asyncio.to_thread(_run_ssh_command, cfg, command, timeout_s)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SSH MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host for SSE/HTTP transports"
    )
    parser.add_argument(
        "--port", type=int, default=8012, help="Port for SSE/HTTP transports"
    )
    args = parser.parse_args()

    if args.transport != "stdio":
        mcp.settings.host = args.host  # type: ignore[attr-defined]
        mcp.settings.port = args.port  # type: ignore[attr-defined]

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
