# keel-telegram-bot [![Build Status](https://img.shields.io/endpoint.svg?url=https%3A%2F%2Factions-badge.atrox.dev%2Fmarkusressel%2Fkeel-telegram-bot%2Fbadge%3Fref%3Dmaster&style=flat)](https://actions-badge.atrox.dev/markusressel/keel-telegram-bot/goto?ref=master) [![Code Climate](https://codeclimate.com/github/markusressel/keel-telegram-bot.svg)](https://codeclimate.com/github/markusressel/keel-telegram-bot) [![PyPI version](https://badge.fury.io/py/keel-telegram-bot.svg)](https://badge.fury.io/py/keel-telegram-bot)

**keel-telegram-bot** is a telegram bot for [Keel](https://keel.sh/).


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

# How to use

## Manual installation

### Install

Install **keel-telegram-bot** using pip:

```shell
pip3 install keel-telegram-bot
```

### Configuration

**keel-telegram-bot** uses [container-app-conf](https://github.com/markusressel/container-app-conf)
to provide configuration via a YAML file as well as ENV variables. Have a look at the 
[documentation about it](https://github.com/markusressel/container-app-conf).

See [keel-telegram-bot_example.yaml](/keel-telegram-bot_example.yaml) for an example in this repo.

### Run

Start the bot by using:

```shell script
keel-telegram-bot
```

## Docker

To run **keel-telegram-bot** using docker you can use the [markusressel/keel-telegram-bot](https://hub.docker.com/r/markusressel/keel-telegram-bot) 
image from DockerHub:

```
sudo docker run -t \
    markusressel/keel-telegram-bot:latest
```

Configure the image using either environment variables, or mount the configuration
file from your host system to `/app/keel-telegram-bot.yaml`.

## Setup

This bot uses the REST api provided by Keel to interact with it
and relies on the Webhook functionality to receive and forward notifications
to telegram chats. On one hand **keel-telegram-bot** acts like the web 
interface, on the other hand it acts like a proxy, both combined into a 
single package.

To get the commands working simply provide all the necessary details of
the configuration file.

To get notifications working you will have to provide the address of 
**keel-telegram-bot** to Keel using the `WEBHOOK_ENDPOINT` env variable.
The simplest way to achieve this is by running both Keel and **keel-telegram-bot**
on the same host and specifying `http://localhost:5000/`.

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
