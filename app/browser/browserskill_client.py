import json
import subprocess

from app.browser.interface import BrowserError


class BrowserSkillClient:
    def __init__(self):
        self.session_id: str | None = None
        self.tab_id: int | None = None

    def _run(
        self,
        command: list[str],
    ) -> str:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=45,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BrowserError(
                "BrowserSkill command failed or timed out. Stop and inspect the "
                "browser; no mutation was retried. Check bsk status for disconnects."
            ) from error

        if result.returncode != 0:
            raise BrowserError(self._describe_failure(command, result))
        return result.stdout.strip()

    @staticmethod
    def _describe_failure(command: list[str], result) -> str:
        # Report bsk's own diagnostic codes/hints, never the arguments (which may
        # hold candidate facts) or raw stderr.
        detail = ""
        try:
            data = json.loads(result.stdout)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            nested = data.get("data") if isinstance(data.get("data"), dict) else {}
            parts = [str(data[k]) for k in ("code", "message", "hint") if isinstance(data.get(k), str)]
            if isinstance(nested.get("reason"), str):
                parts.append("reason=" + nested["reason"])
            detail = "; ".join(parts)
        verb = command[1] if len(command) > 1 else "command"
        return (f"BrowserSkill '{verb}' exited {result.returncode}"
                + (f": {detail}" if detail else "") + ". No mutation was retried.")

    def _json(self, command: list[str]):
        try:
            data = json.loads(self._run([*command, "--json"]))
        except (ValueError, TypeError) as error:
            raise BrowserError("BrowserSkill returned invalid JSON; execution stopped.") from error
        if isinstance(data, dict) and (data.get("ok") is False or data.get("exit_code", 0)):
            raise BrowserError("BrowserSkill reported an error; execution stopped.")
        return data

    def _target(self) -> list[str]:
        if self.session_id is None or self.tab_id is None:
            raise BrowserError("BrowserSkill session/tab is not attached.")
        return ["--session", self.session_id, "--tab-id", str(self.tab_id)]

    def attach(self, session_id: str, tab_id: int) -> None:
        sessions = self._json(["bsk", "session", "list"])
        if not isinstance(sessions, list) or not any(s.get("session_id") == session_id for s in sessions):
            raise BrowserError("Requested BrowserSkill session is no longer active.")
        tabs = self._json(["bsk", "tab", "list", "--session", session_id, "--scope", "agent"])
        if not isinstance(tabs, dict) or not any(
            t.get("tab_id") == tab_id and t.get("scope") == "agent" for t in tabs.get("tabs", [])
        ):
            raise BrowserError("Requested tab does not belong to this agent session.")
        self.session_id, self.tab_id = session_id, tab_id

    def evaluate_readonly(self, expression: str):
        data = self._json(["bsk", "evaluate", expression, *self._target()])
        if not isinstance(data, dict) or data.get("ok") is not True or "value" not in data:
            raise BrowserError("BrowserSkill readback has no confirmed result.")
        return data["value"]

    def fill(self, selector: str, value: str) -> None:
        self._json(["bsk", "fill", "--selector", selector, "--value", value, *self._target()])

    def click(self, selector: str) -> None:
        # Only the adapter exposes this, after checking combobox/option identity.
        self._json(["bsk", "click", "--selector", selector, *self._target()])

    def upload(self, selector: str, path: str) -> None:
        """Deliver a local file through the page's own file chooser trigger."""
        self._json(["bsk", "upload", "--selector", selector, "--file", path, *self._target()])

    def start(self) -> None:
        if self.session_id is not None:
            raise RuntimeError(
                "BrowserSkill session is already running."
            )

        data = self._json(
            [
                "bsk",
                "session",
                "start",
                "--no-focus",
            ]
        )

        if not isinstance(data, dict) or not isinstance(data.get("session_id"), str) or not data["session_id"]:
            raise BrowserError("BrowserSkill did not confirm a session ID.")
        self.session_id = data["session_id"]
        tabs = self._json(["bsk", "tab", "list", "--session", self.session_id, "--scope", "agent"])
        if not isinstance(tabs, dict):
            raise BrowserError("BrowserSkill returned invalid tab state; session left open.")
        active = [t for t in tabs.get("tabs", []) if t.get("scope") == "agent" and t.get("active")]
        if len(active) != 1:
            raise BrowserError("Cannot identify one active agent tab; session left open.")
        self.tab_id = active[0]["tab_id"]

    def open(
        self,
        url: str,
    ) -> None:
        if self.session_id is None:
            raise RuntimeError(
                "BrowserSkill has not been started."
            )

        self._json(
            [
                "bsk",
                "navigate",
                url,
                *self._target(),
            ]
        )

    def observe(self) -> str:
        if self.session_id is None:
            raise RuntimeError(
                "BrowserSkill has not been started."
            )

        return self._run(
            [
                "bsk",
                "observe",
                *self._target(),
            ]
        )

    def screenshot(
        self,
        output_path: str,
    ) -> None:
        if self.session_id is None:
            raise RuntimeError(
                "BrowserSkill has not been started."
            )

        self._run(
            [
                "bsk",
                "screenshot",
                *self._target(),
                "--out",
                output_path,
            ]
        )

    def close(self) -> None:
        if self.session_id is None:
            return

        self._run(
            [
                "bsk",
                "session",
                "stop",
                self.session_id,
            ]
        )

        self.session_id = None
        self.tab_id = None
