# Guestbook — Docker and Kubernetes final project

Two versions of the IBM Skills Network Guestbook run on port 3000. The v1 image uses the
regular page title and the v2 image changes both the browser title and the heading.
Kubernetes scales the workload using a CPU-based Horizontal Pod Autoscaler, rolls the
deployment to v2 with lower CPU requests and limits, then rolls back to v1.

The application builds on the [IBM Skills Network starter](https://github.com/ibm-developer-skills-network/guestbook)
and follows the [Guestbook lab instructions](https://cf-courses-data.static.labs.skills.network/g6haPxvVsEJqFaCYdGroNw/instructions-Mark-v1.md).
The standalone deployment stores entries in memory per pod. The starter's optional Redis
support remains available when its Redis services are configured.

## Run the IBM lab

In Coursera, open **Build and Deploy a Simple Guestbook App** and launch the hands-on lab.
Run the script from the project checkout with Docker, `ibmcloud` and `kubectl` already
authenticated to the assigned lab. The script uses the current Kubernetes namespace or
the value passed as `--namespace`. It verifies that the `guestbook` resources and v1/v2
tags are available for a fresh exercise before creating them.

```bash
python3 run_lab.py
```

The script prints an `evidence/` directory. It pushes both versions to
`us.icr.io/<sn-labs-namespace>/guestbook`, applies the manifests, waits for a measured
increase in replicas, and captures the CPU settings before and after the update. Traffic
uses a short-lived job that targets the Guestbook service inside the assigned namespace.
The script records the ReplicaSets after rolling back.

Kubernetes may initially show **0** under **REPLICAS** because the autoscaler has not seen
the target workload yet. Its configured **MINPODS** remains **1**.

## What to submit

The form has ten text fields worth **15 points**. Paste the file contents into the
matching field. The three source answers are available in `submission/`. The seven
terminal answers must come from the lab directory printed by `run_lab.py`.

| Question | Points | File | What it shows |
| --- | ---: | --- | --- |
| 1 | 1 | `Dockerfile` | Multi-stage build, binary and static-file `COPY` commands, and `EXPOSE 3000`. |
| 2 | 1 | `crimages.txt` | `ibmcloud cr images` listing the assigned registry repository with tag `v1`. |
| 3 | 1 | `app.txt` | Source with `Guestbook - v1` in both `<title>` and `<h1>`. |
| 4 | 1 | `hpa.txt` | Initial HPA table with target, min and max pods, replica count, and age. |
| 5 | 2 | `hpa2.txt` | HPA table with more than one replica after load. |
| 6 | 2 | `upguestbook.txt` | Actual `docker push` output for `v2`, including the final digest. |
| 7 | 1 | `deployment.txt` | `kubectl apply -f deployment.yml` confirming the deployment was updated. |
| 8 | 2 | `up-app.txt` | Source with `Guestbook - v2` in both `<title>` and `<h1>`. |
| 9 | 2 | `rev.txt` | Rollout history and the CPU request and limit for both revisions. |
| 10 | 2 | `rs.txt` | `kubectl get rs` after rollback, with two Guestbook ReplicaSets. |

## Run locally

Building a container locally requires a Linux-container Docker engine.

```bash
cd v1/guestbook
docker build -t guestbook:v1 .
docker run --rm -p 127.0.0.1:3000:3000 guestbook:v1
```

With Go 1.26, run `go run .` from the same folder to test the app directly.
The second version's source is at `versions/v2/index.html`, and the lab script uses it
in a separate build context while keeping the original v1 source available.
