# keel-telegram-bot [![Build Status](https://travis-ci.com/markusressel/keel-telegram-bot.svg?branch=master)](https://travis-ci.com/markusressel/keel-telegram-bot) [![PyPI version](https://badge.fury.io/py/keel-telegram-bot.svg)](https://badge.fury.io/py/keel-telegram-bot)

**keel-telegram-bot** is a telegram bot for [Keel](https://keel.sh/).

# Features

* [ ] Receive notifications (via Webhook)
* [ ] List pending approvals
* [ ] Approve pending approvals
* [ ] Reject pending approvals

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
