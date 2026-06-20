

### Step by step (How to execute)

Docker image build
```bash
$ docker build --no-cache \
  --platform linux/amd64 \
  -t wwiras/qahbn-peer:v7 \
  -f app/Dockerfile app
```

Image Push
```bash
$ docker push wwiras/qahbn-peer:v7
```

Create GKE k8s cluster
```bash
$ gcloud container clusters create bcgossip-cluster \
  --zone=us-central1-a --num-nodes 7 \
  --machine-type e2-medium --quiet
```

Running the experiment
```bash
$ IMAGE=wwiras/qahbn-peer:v7 ./scripts/run_exp12_compare.sh
```

After experiment Clean deployment
```bash
$ helm uninstall ahbn -n ahbn-exp12 || true
$ kubectl delete namespace ahbn-exp12 --ignore-not-found=true
```

List of all GKE clusters
```bash
$ gcloud container clusters list
```

Remove GKE cluster
```bash
$ gcloud container clusters delete  bcgossip-cluster --zone us-central1-a
```