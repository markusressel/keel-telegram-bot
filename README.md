# keel-telegram-bot [![Build Status](https://img.shields.io/endpoint.svg?url=https%3A%2F%2Factions-badge.atrox.dev%2Fmarkusressel%2Fkeel-telegram-bot%2Fbadge%3Fref%3Dmaster&style=flat)](https://actions-badge.atrox.dev/markusressel/keel-telegram-bot/goto?ref=master) [![Code Climate](https://codeclimate.com/github/markusressel/keel-telegram-bot.svg)](https://codeclimate.com/github/markusressel/keel-telegram-bot) [![PyPI version](https://badge.fury.io/py/keel-telegram-bot.svg)](https://badge.fury.io/py/keel-telegram-bot)

**keel-telegram-bot** is a telegram bot for a forked version of [Keel](https://github.com/markusressel/keel).


<p align="center">
  <img src="/screenshots/commands.png" width="400"> <img src="/screenshots/approval.png" width="400"> 
</p>

# Features

* [x] Receive notifications (via Webhook)
* [x] List approvals
* [x] Approve pending approvals
* [x] Reject pending approvals
* [x] Delete archived approvals
* [x] Permission handling based on telegram usernames
* [x] Filter visible approvals on a per-chat basis
* [x] Helm chart updates for HelmChart objects of the k3s helm-controller (optional)

# How it works

This bot uses the REST api provided by Keel to interact with it
and relies on the Webhook functionality to receive and forward notifications
to telegram chats. On one hand **keel-telegram-bot** acts like the web
interface of keel, on the other hand it acts like a relay for keel notifications, both combined into a
single package.

To get telegram commands working simply provide all the necessary details of
the configuration file.

To get notifications working you will have to provide the address of 
**keel-telegram-bot** to Keel using the `WEBHOOK_ENDPOINT` env variable.
The simplest way to achieve this is by running both Keel and **keel-telegram-bot**
on the same host and specifying `http://localhost:5000/`.

## Helm chart updates

Keel does not update Helm chart versions. If enabled (`helm_charts.enabled`), **keel-telegram-bot**
checks the `HelmChart` objects (`helm.cattle.io/v1`) of the
[k3s helm-controller](https://docs.k3s.io/helm) for new chart versions:

* The check runs once per `helm_charts.interval` (default: once a day) and when using the `/helmcheck`
  command. `/helmcharts` lists all HelmCharts with their current and latest version.
* For each HelmChart, the `index.yaml` of `spec.repo` is fetched and searched for newer versions of `spec.chart`.
  Pre-releases are ignored, unless the current version is a pre-release itself.
* HelmCharts managed by k3s itself (f.ex. the bundled traefik), HelmCharts without `spec.repo` or `spec.version`
  and OCI charts (`oci://...`) are skipped.
* A minor or patch update is announced with the buttons "Upgrade" and "Ignore". "Upgrade" sets `spec.version`
  of the HelmChart, waits for the helm-controller install job (`helm-install-<name>`) and reports success, or
  failure including the end of the job log. "Ignore" stops notifications about this version.
* A major update is only announced, because it usually needs manual steps (CRD updates, upgrade notes).
  If there is a newer version within the current major version, the notification offers an upgrade to it.
* Updates of HelmCharts in `helm_charts.notify_only` are only announced, with an "Ignore" button but no
  "Upgrade" button. The same applies automatically to charts that ship CRDs which helm does not upgrade,
  unless the HelmChart enables the chart's own CRD upgrade (`spec.set` or `spec.valuesContent`):
  `kube-prometheus-stack` with `crds.upgradeJob.enabled: true`.
* Announced and ignored versions are stored in `helm_charts.state_path`. Put this file on a persistent volume,
  otherwise pending updates are announced again after a restart and ignored versions are forgotten.
* Only users in `telegram.admin_usernames` can press the buttons, in one of the `telegram.chat_ids`.
  The per-chat `filters` apply to the identifier `helmchart/<targetNamespace>/<name>`.

The ServiceAccount of the bot needs the following permissions in the namespace of the HelmCharts:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: keel-telegram-bot-helm-charts
  namespace: kube-system
rules:
  - apiGroups: ["helm.cattle.io"]
    resources: ["helmcharts"]
    verbs: ["get", "list", "watch", "patch"]
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: keel-telegram-bot-helm-charts
  namespace: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: keel-telegram-bot-helm-charts
subjects:
  - kind: ServiceAccount
    name: keel
    namespace: keel
```

Inside the cluster the bot uses the ServiceAccount token, outside of it the current kubeconfig context.

# How to use

Configure the docker image using either environment variables, or mount the configuration
file from your host system to `/app/keel-telegram-bot.yaml`.

## Configuration

**keel-telegram-bot** uses [container-app-conf](https://github.com/markusressel/container-app-conf)
to provide configuration via a YAML file as well as ENV variables. Have a look at the 
[documentation about it](https://github.com/markusressel/container-app-conf).

See [keel-telegram-bot_example.yaml](/keel-telegram-bot_example.yaml) for an example in this repo.

## Run

To run **keel-telegram-bot** using docker you can use the [ghcr.io/markusressel/keel-telegram-bot](https://github.com/markusressel/keel-telegram-bot/pkgs/container/keel-telegram-bot) image:

```
sudo docker run -t \
    ghcr.io/markusressel/keel-telegram-bot:latest
```

# Contributing

GitHub is for social coding: if you want to write code, I encourage contributions through pull requests from forks
of this repository. Create GitHub tickets for bugs and new features and comment on the ones that you are interested in.

# License

```text
keel-telegram-bot by Markus Ressel
Copyright (C) 2020  Markus Ressel

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
```
