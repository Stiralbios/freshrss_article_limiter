IMAGE_NAME := freshrss-article-limiter

.PHONY: build dry-run run help

build:
	docker build -t $(IMAGE_NAME) .

dry-run: build
	docker run --rm \
		-v $(PWD)/.env:/app/.env:ro \
		-v $(PWD)/user_prompt.txt:/app/user_prompt.txt:ro \
		$(IMAGE_NAME) \
		--dry-run --rate-limiter 1 --nb-evaluated 5

run: build
	docker run --rm \
		-v $(PWD)/.env:/app/.env:ro \
		-v $(PWD)/user_prompt.txt:/app/user_prompt.txt:ro \
		$(IMAGE_NAME)

help:
	@echo "Available targets:"
	@echo "  make build   - Build the Docker image"
	@echo "  make dry-run - Run in dry-run mode (default, evaluates 5 articles)"
	@echo "  make run     - Run in live mode (processes all unread articles)"
