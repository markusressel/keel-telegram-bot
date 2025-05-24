
docker-image:
	docker build . --file Dockerfile --tag markusressel/keel-telegram-bot:latest

redeploy:
	podname=$$(kubectl get pods -n keel -o namepods --no-headers -o custom-columns=":metadata.name" | grep keel); \
	kubectl delete pod -n keel $$podname

test:
	pytest
