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
* [x] Check the registry for new image versions on demand (`/poll`, "Check now" button), needs a Keel build
      with `POST /v1/poll`

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
* Minor and patch updates can be upgraded automatically instead, see [Automatic upgrades](#automatic-upgrades).
* Updates of HelmCharts in `helm_charts.notify_only` are only announced, with an "Ignore" button but no
  "Upgrade" button. The same applies automatically to charts that ship CRDs which helm does not upgrade,
  unless the HelmChart enables the chart's own CRD upgrade (`spec.set` or `spec.valuesContent`):
  `kube-prometheus-stack` with `crds.upgradeJob.enabled: true`.
* Announced and ignored versions are stored in `helm_charts.state_path`. Put this file on a persistent volume,
  otherwise pending updates are announced again after a restart and ignored versions are forgotten.
  An upgrade that is running during a restart is stored in the database (see below) and watched again
  afterwards, so its notification does not stay on "Upgrading to ..." forever.
* Only users in `telegram.admin_usernames` can press the buttons, in one of the `telegram.chat_ids`.
  The per-chat `filters` apply to the identifier `helmchart/<targetNamespace>/<name>`.

### Automatic upgrades

`helm_charts.auto_upgrade` lists the update levels that are upgraded without pressing "Upgrade":

```yaml
keel-telegram-bot:
  helm_charts:
    enabled: true
    # upgrade minor and patch updates automatically, majors are still only announced
    auto_upgrade:
      - minor
      - patch
    # optional: HelmCharts (by name) that keep the "Upgrade" button
    auto_upgrade_exclude:
      - loki
```

* The level is relative to the current version: `patch` is a newer version with the same major and minor
  version (`1.2.3` -> `1.2.5`), `minor` one with the same major and a higher minor version (`1.2.3` -> `1.4.1`).
  `major` is not accepted, the bot refuses to start with it. The default is an empty list: every upgrade
  needs a button press.
* The bot upgrades to the newest allowed version: with `minor`, the newest version within the current major
  version; with only `patch`, the newest version within the current minor version. Newer versions that are
  left (f.ex. a major update, or a minor update with only `patch` allowed) are announced as usual, relative
  to the new version.
* An automatic upgrade works like pressing "Upgrade": it sets `spec.version`, sends a notification
  "Automatic helm chart upgrade" to each chat (respecting the `filters`), waits for the install job and replies
  with the outcome, including the end of the job log on failure. It is watched again after a restart, too.
* Never upgraded automatically: pre-releases, ignored versions, HelmCharts in `helm_charts.notify_only` or
  `helm_charts.auto_upgrade_exclude`, charts with CRDs that are not upgraded (see above), charts that no chat
  would be notified about, and charts with an upgrade still running.
* A version whose upgrade failed, timed out or could not be watched (automatic or from Telegram) is never
  upgraded automatically again. It stays in `spec.version`, so nothing is retried; if the HelmChart is set back
  to an older version, the failed version is announced with an "Upgrade" button instead. A newer version is
  upgraded automatically again. Failed versions are stored in `helm_charts.state_path` as well.

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

## Notifications

A new approval is announced in a short form: Keel's message with the versions, the votes (only when more
than one is required or some were given) and the expiry time. The approval id is in the data of the buttons,
so the message does not need to show it. `/approvals` and the other commands list all properties
(id, identifier, versions, votes, expiry).

Approval requests (while pending) and Keel notifications have a "Check now" button, see
[Polling on demand](#polling-on-demand).

Times are shown in the local time zone of the bot. Set the `TZ` environment variable (f.ex.
`TZ=Europe/Berlin`), the default is UTC.

## Polling on demand

Keel checks the registry of a workload only on its poll schedule (`keel.sh/pollSchedule`, often once a day).
`/poll` asks Keel to check now:

* `/poll` checks all images watched by Keel's poll trigger. This can take up to a minute. The reply lists only
  the images with a newer version or an error, and counts the ones that are up to date:
  ```
  Polled 23 images: 1 newer, 1 failed, 21 up to date
  ghcr.io/music-assistant/server: newer version found (2.5.0), update or approval follows
  ghcr.io/example/app: error: unauthorized
  ```
* `/poll <identifier>` checks the images of one resource. Part of a name works too (f.ex. `/poll music`), the
  bot then offers the matching resources to pick from, like `/update`.
  ```
  Polled deployment/homeassistant/music-assistant:
  ghcr.io/music-assistant/server: up to date
  ```
* The "Check now" button of a pending approval request and of a Keel notification checks the resource of that
  message and replies to it with the result.

A newer version found is handed to Keel, which then updates the workload or asks for approval as usual, so the
update notification or approval request follows as its own message.

Only users in `telegram.admin_usernames` can use the command and the button, in one of the
`telegram.chat_ids`, and the per-chat `filters` apply.

This needs a Keel build with the `POST /v1/poll` endpoint, f.ex. the fork
[markusressel/keel](https://github.com/markusressel/keel); upstream Keel does not have it.
Against a Keel without it, the bot replies "Keel has no POST /v1/poll endpoint...". A resource or image that is
not watched by Keel's poll trigger (f.ex. a workload with `keel.sh/trigger: default` and no poll schedule) gets
"... is not watched by Keel's poll trigger". While a check of all images is running, another one is refused
until it is done.

## Database

The bot keeps a little state in a database: the Telegram messages of approval notifications (so their buttons
follow the approval, also after a restart), which approval was announced in which chat (so an approval that
appeared while the bot was down is announced afterwards, and none twice) and running Helm chart upgrades.

`database.url` is a [SQLAlchemy URL](https://docs.sqlalchemy.org/en/20/core/engines.html#database-urls):

* SQLite (default, `sqlite:///keel-telegram-bot.db`): a file, nothing to set up. Put it on a persistent volume.
* PostgreSQL: `postgresql://user:password@host:5432/database`, for an existing server.

The schema is created and updated on start (Alembic). The first start with a new database does not announce
the approvals that are pending at that moment, they were announced before.

## Run

To run **keel-telegram-bot** using docker you can use the [ghcr.io/markusressel/keel-telegram-bot](https://github.com/markusressel/keel-telegram-bot/pkgs/container/keel-telegram-bot) image:

```shell
docker volume create keel-telegram-bot-data
docker run -d --name keel-telegram-bot --restart unless-stopped \
    -p 5000:5000 \
    -v "$(pwd)/keel-telegram-bot.yaml:/app/keel-telegram-bot.yaml:ro" \
    -v keel-telegram-bot-data:/app/data \
    ghcr.io/markusressel/keel-telegram-bot:latest
```

* `keel-telegram-bot.yaml` holds the configuration, see above.
* Port `5000` receives the notifications of Keel. Point Keel's `WEBHOOK_ENDPOINT` at it,
  f.ex. `http://<host>:5000/`.
* `/app/data` keeps the state of the Helm chart updates and the SQLite database. Set
  `helm_charts.state_path` to `/app/data/helm-chart-state.json` and `database.url` to
  `sqlite:////app/data/keel-telegram-bot.db`. Without a volume, pending Helm chart updates are announced
  again after a restart, ignored versions are forgotten, the buttons of open approval messages stay as they
  are and approvals that appeared while the bot was down are not announced.

Keel needs a volume too: it keeps its approvals in `/data/keel.db`. Without a volume, every restart
of Keel loses the pending approvals, and Keel sends all of them again with new ids, so the bot
announces every pending update again.

### Kubernetes

Run the bot as a second container in the Keel pod: the bot reaches the Keel API on `localhost:9300`
and Keel reaches the webhook on `http://localhost:5000/`. One volume can hold the state of both
containers with a `subPath` each:

```yaml
containers:
  - name: keel
    # ...
    volumeMounts:
      - name: data
        mountPath: /data
        subPath: keel
  - name: telegram-bot
    image: ghcr.io/markusressel/keel-telegram-bot:latest
    volumeMounts:
      - name: config
        mountPath: /app/keel-telegram-bot.yaml
        subPath: keel-telegram-bot.yaml
      - name: data
        mountPath: /app/data
        subPath: telegram-bot
volumes:
  - name: config
    configMap:
      name: keel-telegram-bot
  - name: data
    persistentVolumeClaim:
      claimName: keel-data
```

For Helm chart updates the ServiceAccount of the pod needs the RBAC rules from
[Helm chart updates](#helm-chart-updates).

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
