"""Run only against a disposable Compose project; deliberately interrupts its worker."""

import argparse
import json
import subprocess
import time
from pathlib import Path
import httpx


def wait_for(predicate, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise AssertionError("Experiment timed out")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", default=".env.validation")
    parser.add_argument("--base-url", default="http://127.0.0.1:8800")
    parser.add_argument("--output", default="docs/validation/restart-experiment.json")
    args = parser.parse_args()
    if args.project not in ("integrationops-validation", "integrationops-ci"):
        raise ValueError(
            "This interruption experiment is restricted to the disposable validation project"
        )

    def compose(*arguments):
        subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                args.env_file,
                "-p",
                args.project,
                *arguments,
            ],
            check=True,
        )

    with httpx.Client(base_url=args.base_url, timeout=10) as client:
        wait_for(lambda: client.get("/api/health/ready").status_code == 200)
        examples = client.post("/api/demo").json()
        payment = next(item for item in examples if item["demo_key"] == "payment")
        wait_for(
            lambda: (
                len(client.get(f"/api/integrations/{payment['id']}/checks").json()) >= 1
            )
        )
        client.post(
            "/api/demo/scenario", json={"service": "payment", "mode": "timeout"}
        ).raise_for_status()
        response = client.post(f"/api/integrations/{payment['id']}/check")
        assert response.status_code == 202, response.text
        run_id = response.json()["execution_id"]
        wait_for(
            lambda: client.get("/api/runs/" + run_id).json()["status"] == "RUNNING"
        )
        started = time.monotonic()
        compose("kill", "-s", "SIGKILL", "worker")
        compose("start", "worker")
        recovered = wait_for(
            lambda: client.get("/api/runs/" + run_id).json().get("check")
        )
        elapsed = time.monotonic() - started
        run = client.get("/api/runs/" + run_id).json()
        assert run["attempts"] >= 2, run
        assert (
            recovered["execution_id"] == run_id
            and recovered["failure_type"] == "TIMEOUT"
        )
        history = client.get(f"/api/integrations/{payment['id']}/checks").json()
        assert sum(item["execution_id"] == run_id for item in history) == 1
        client.post(
            "/api/demo/scenario", json={"service": "payment", "mode": "server_error"}
        ).raise_for_status()

        def check():
            response = client.post(f"/api/integrations/{payment['id']}/check")
            assert response.status_code == 202, response.text
            return wait_for(
                lambda: (
                    client.get("/api/runs/" + response.json()["execution_id"])
                    .json()
                    .get("check")
                )
            )

        for _ in range(3):
            check()
        assert any(
            item["status"] == "OPEN" for item in client.get("/api/incidents").json()
        )
        before = client.get("/metrics").text
        assert "integrationops_active_incidents" in before
        compose("restart", "api")
        wait_for(lambda: client.get("/api/health/ready").status_code == 200)
        after = client.get("/metrics").text
        from prometheus_client.parser import text_string_to_metric_families

        def sample(text, name):
            return next(
                sample.value
                for family in text_string_to_metric_families(text)
                for sample in family.samples
                if sample.name == name
            )

        assert sample(after, "integrationops_active_incidents") >= 1
        assert any(
            item["status"] == "OPEN" for item in client.get("/api/incidents").json()
        )
        client.post(
            "/api/demo/scenario", json={"service": "payment", "mode": "healthy"}
        ).raise_for_status()
        for _ in range(2):
            check()
        result = {
            "status": "passed",
            "worker_interruption": "SIGKILL",
            "reused_run_id": True,
            "persisted_outcomes_for_interrupted_run": 1,
            "run_attempts": run["attempts"],
            "recovery_elapsed_seconds": round(elapsed, 2),
            "persisted_incidents_survive_api_restart": True,
            "metrics_survive_api_restart": True,
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
