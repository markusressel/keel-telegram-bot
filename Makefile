
docker-image:
	docker build . --file Dockerfile --tag markusressel/keel-telegram-bot:latest

test:
	pytest
