"""Build, push, deploy, scale, and roll back Guestbook in an assigned IBM lab."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
from shlex import join
from shutil import copyfile, copytree
import subprocess
from tempfile import TemporaryDirectory
import time


ROOT = Path(__file__).resolve().parent
V1 = ROOT / "v1" / "guestbook"
V2 = ROOT / "versions" / "v2"
MANIFESTS = ROOT / "kubernetes"


def run(*args, cwd=None, timeout=400, show=True):
    """Return actual combined command output, with optional console progress."""
    if show:
        print("$ " + join(args), flush=True)
    result = subprocess.run(
        args, cwd=cwd, timeout=timeout, check=False, text=True,
        encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if show and result.stdout:
        print(result.stdout, end="", flush=True)
    if result.returncode:
        raise RuntimeError(f"{join(args)} exited with {result.returncode}\n{result.stdout}")
    return result.stdout


def save(directory, filename, entries):
    """Write the exact command and its observed output to an evidence file."""
    content = "\n\n".join("$ " + join(args) + "\n" + text.rstrip() for args, text in entries)
    path = directory / f"{filename}.txt"
    path.write_text(content + "\n", encoding="utf-8")
    print(f"Saved {path.name}", flush=True)


def record(directory, filename, *args, **kwargs):
    text = run(*args, **kwargs)
    save(directory, filename, [(args, text)])
    return text


def deployment_revision(kube):
    data = json.loads(run(*kube, "get", "deployment", "guestbook", "-o", "json", show=False))
    return data["metadata"]["annotations"]["deployment.kubernetes.io/revision"]


def autoscale(directory, kube):
    """Run bounded traffic within the lab namespace and save an observed scale-up."""
    command = (*kube, "get", "hpa", "guestbook")
    job = run(*kube, "create", "-f", str(MANIFESTS / "load.yml"), "-o", "name").strip()
    if not re.fullmatch(r"job\.batch/guestbook-load-[a-z0-9]+", job):
        raise RuntimeError(f"Unexpected load job response {job!r}")
    try:
        deadline = time.monotonic() + 265
        while time.monotonic() < deadline:
            hpa = json.loads(run(*command, "-o", "json", show=False))
            if hpa.get("status", {}).get("currentReplicas", 0) > 1:
                record(directory, "hpa2", *command)
                return
            time.sleep(8)
        run(*kube, "describe", "hpa", "guestbook")
        raise RuntimeError("No HPA scale-up was observed before the load deadline.")
    finally:
        run(*kube, "delete", job, "--ignore-not-found", "--wait=false")


def collect(namespace):
    """Capture submission evidence in a fresh, already authenticated lab namespace."""
    kube = ("kubectl", "--namespace", namespace)
    repository = f"us.icr.io/{namespace}/guestbook"
    image_v1, image_v2 = f"{repository}:v1", f"{repository}:v2"

    run("docker", "version", "--format", "{{.Server.Version}}", timeout=20)
    run(*kube, "get", "--raw", "/apis/metrics.k8s.io/v1beta1", timeout=20, show=False)
    existing = run(
        *kube, "get", "deployment,service,hpa", "guestbook", "--ignore-not-found", "-o", "name",
        timeout=20,
    ).strip()
    if existing:
        raise RuntimeError(f"Existing guestbook resources in {namespace}:\n{existing}")
    registry = run("ibmcloud", "cr", "images", "--restrict", repository, timeout=45)
    if re.search(rf"(?m)^[ \t]*{re.escape(repository)}[ \t]+v[12]\b", registry):
        raise RuntimeError(f"The registry already contains {repository}:v1 or :v2.")
    run("ibmcloud", "cr", "login", timeout=45)

    directory = ROOT / "evidence" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True)
    print(f"Evidence folder: {directory}", flush=True)
    copyfile(V1 / "Dockerfile", directory / "Dockerfile")
    copyfile(V1 / "public" / "index.html", directory / "app.txt")
    copyfile(V2 / "index.html", directory / "up-app.txt")
    print("Starting v1 image build", flush=True)
    run("docker", "build", "-t", image_v1, str(V1), timeout=600)
    run("docker", "push", image_v1)
    command = ("ibmcloud", "cr", "images", "--restrict", repository)
    registry = run(*command)
    if not re.search(rf"(?m)^[ \t]*{re.escape(repository)}[ \t]+v1\b", registry):
        raise RuntimeError("The IBM Container Registry listing did not show the v1 tag.")
    save(directory, "crimages", [(command, registry)])

    run(*kube, "create", "-f", str(MANIFESTS / "hpa.yml"))
    record(directory, "hpa", *kube, "get", "hpa", "guestbook")
    run(*kube, "apply", "-f", str(MANIFESTS / "service.yml"))

    autoscale_error = None
    with TemporaryDirectory(prefix="guestbook-build-") as scratch:
        build = Path(scratch)
        deployment = build / "deployment.yml"
        deployment.write_text(
            (V1 / "deployment.yml").read_text().replace("GUESTBOOK_IMAGE", image_v1),
            encoding="utf-8",
        )
        run(*kube, "apply", "-f", "deployment.yml", cwd=build)
        run(*kube, "rollout", "status", "deployment/guestbook", "--timeout=240s")
        first_revision = deployment_revision(kube)

        try:
            autoscale(directory, kube)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            autoscale_error = error
            print(f"Task 5 pending: {error}", flush=True)

        # Release the scaled-up pods before rolling out a second ReplicaSet.
        run(*kube, "delete", "hpa", "guestbook")
        run(*kube, "scale", "deployment", "guestbook", "--replicas=1")
        downscale_deadline = time.monotonic() + 100
        while time.monotonic() < downscale_deadline:
            pods = json.loads(run(*kube, "get", "pods", "-l", "app=guestbook",
                                  "-o", "json", show=False))["items"]
            if len(pods) == 1:
                break
            time.sleep(5)
        else:
            raise RuntimeError("Extra Guestbook pods did not terminate after scale-down.")

        context_v2 = build / "v2"
        copytree(V1, context_v2)
        copyfile(V2 / "index.html", context_v2 / "public" / "index.html")
        run("docker", "build", "-t", image_v2, str(context_v2), timeout=600)
        push = ("docker", "push", image_v2)
        output = run(*push)
        if not re.search(r"digest:\s+sha256:[0-9a-f]{64}", output):
            raise RuntimeError("Docker did not report a digest for the v2 push.")
        save(directory, "upguestbook", [(push, output)])

        deployment.write_text(
            (V2 / "deployment.yml").read_text().replace("GUESTBOOK_IMAGE", image_v2),
            encoding="utf-8",
        )
        record(directory, "deployment", *kube, "apply", "-f", "deployment.yml", cwd=build)
        run(*kube, "rollout", "status", "deployment/guestbook", "--timeout=240s")
        second_revision = deployment_revision(kube)
        history = (*kube, "rollout", "history", "deployment/guestbook")
        details = [history, (*history, f"--revision={first_revision}"),
                   (*history, f"--revision={second_revision}")]
        save(directory, "rev", [(command, run(*command)) for command in details])

        run(*kube, "rollout", "undo", "deployment/guestbook", f"--to-revision={first_revision}")
        run(*kube, "rollout", "status", "deployment/guestbook", "--timeout=240s")
        images = run(*kube, "get", "deployment", "guestbook", "-o",
                     "jsonpath={.spec.template.spec.containers[0].image}", show=False)
        if images != image_v1:
            raise RuntimeError(f"Rollback image was {images!r}, expected {image_v1!r}.")
        rs = (*kube, "get", "rs", "-l", "app=guestbook")
        sets = json.loads(run(*rs, "-o", "json", show=False))["items"]
        if len(sets) != 2 or sorted(item["spec"].get("replicas", 0) for item in sets)[0] != 0:
            raise RuntimeError("Expected two ReplicaSets and one scaled to zero following rollback.")
        record(directory, "rs", *rs)

    if autoscale_error is not None:
        raise RuntimeError(f"Saved the other evidence to {directory}. Task 5 remains pending.")
    print(f"Evidence complete: {directory}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default=os.environ.get("MY_NAMESPACE"))
    args = parser.parse_args()
    namespace = args.namespace
    if namespace is None:
        namespace = run(
            "kubectl", "config", "view", "--minify", "-o", "jsonpath={..namespace}",
            timeout=20, show=False,
        ).strip()
    if not re.fullmatch(r"sn-labs-[a-z0-9]([a-z0-9-]*[a-z0-9])?", namespace or ""):
        parser.error("Pass the lab's assigned sn-labs namespace using --namespace.")
    try:
        collect(namespace)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
