FROM nousresearch/hermes-agent:main

USER root
RUN apt-get update &&     apt-get install -y --no-install-recommends         jq         unzip         diffutils         socat         zip &&     apt-get clean &&     rm -rf /var/lib/apt/lists/*
USER hermes
